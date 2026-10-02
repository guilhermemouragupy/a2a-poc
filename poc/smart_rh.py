"""Agente Smart RH — servidor A2A feito com o SDK oficial (a2a-sdk).

Publica o Agent Card, recebe mensagens via JSON-RPC, cria uma Task e
entrega a resposta como Artifact. Quem responde é um LLM via OpenRouter
(chave no arquivo .env); se ele falhar, a resposta é montada direto dos
dados fictícios.

Uso:  python smart_rh.py [--port 9999] [--offline]
"""

import argparse
import asyncio
import json
import os
import re
import socket
import ssl
import sys
import time
from pathlib import Path

import httpx
import truststore
import uvicorn
from dotenv import load_dotenv
from starlette.applications import Starlette

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Part,
    Task,
    TaskState,
    TaskStatus,
)

load_dotenv(Path(__file__).parent / ".env")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELO_PADRAO = "z-ai/glm-5.3-flash"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
MODELO = os.environ.get("OPENROUTER_MODEL") or MODELO_PADRAO
TIMEOUT_LLM = 20  # segundos; passou disso, usa a resposta offline
# Usa os certificados do sistema (keychain do macOS), como o curl: a rede
# corporativa inspeciona TLS com uma CA própria que o certifi não conhece.
SSL_SISTEMA = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
# Quando o provedor está congestionado ele responde 429/502/503; uma nova tentativa logo depois
# costuma funcionar. Esperas (s) entre as tentativas:
ESPERAS = (0.7, 1.5, 3.0)
REPETIR = {429, 502, 503}

AZUL, VERDE, AMARELO, CINZA, NEGRITO, RESET = (
    "\033[34m", "\033[32m", "\033[33m", "\033[90m", "\033[1m", "\033[0m",
)

# Dados fictícios — só para a demo.
TIMES = {
    "Plataforma": {"headcount": 12, "senioridade": {"sênior": 7, "pleno": 4, "júnior": 1}, "desligamentos_6_meses": 1},
    "Dados": {"headcount": 8, "senioridade": {"sênior": 3, "pleno": 3, "júnior": 2}, "desligamentos_6_meses": 2},
    "Produto": {"headcount": 15, "senioridade": {"sênior": 5, "pleno": 7, "júnior": 3}, "desligamentos_6_meses": 0},
}


def log(cor: str, texto: str) -> None:
    print(f"{CINZA}{time.strftime('%H:%M:%S')}{RESET} {cor}{texto}{RESET}", flush=True)


# ---------- O "cérebro": LLM via OpenRouter, com fallback offline ----------

def resposta_offline(pergunta: str) -> str:
    """Resposta montada só com os dados, sem LLM."""
    for nome, dados in TIMES.items():
        if nome.lower() in pergunta.lower():
            s = dados["senioridade"]
            return (
                f"O time de {nome} tem {dados['headcount']} pessoas "
                f"({s['sênior']} sênior, {s['pleno']} pleno, {s['júnior']} júnior) "
                f"e teve {dados['desligamentos_6_meses']} desligamento(s) nos últimos 6 meses."
            )
    return f"Tenho dados dos times {', '.join(TIMES)}. Sobre qual deles você quer saber?"


async def com_novas_tentativas(chamada, esperas=ESPERAS) -> httpx.Response:
    """Faz a chamada e, se o provedor estiver congestionado, tenta de novo algumas vezes."""
    for espera in (*esperas, None):
        resposta = await chamada()
        if resposta.status_code not in REPETIR or espera is None:
            return resposta
        await asyncio.sleep(espera)


async def perguntar_llm(pergunta: str, timeout: float = TIMEOUT_LLM) -> str:
    instrucoes = (
        "Você é o Agente Smart RH. Responda em português, em no máximo 3 frases, "
        "usando apenas os dados abaixo. Pode fazer contas e comparações entre os times. "
        "Se a pergunta não puder ser respondida com esses dados, diga isso claramente. Texto simples, sem markdown.\n\n"
        f"Dados dos times: {json.dumps(TIMES, ensure_ascii=False)}"
    )
    async with httpx.AsyncClient(timeout=timeout, verify=SSL_SISTEMA) as client:
        resposta = await com_novas_tentativas(lambda: client.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "X-Title": "POC A2A"},
            json={
                "model": MODELO,
                "reasoning": {"effort": "minimal"},  # o GLM não deixa desligar o raciocínio; o mínimo responde em <1s
                "messages": [
                    {"role": "system", "content": instrucoes},
                    {"role": "user", "content": pergunta},
                ],
            },
        ))
        resposta.raise_for_status()
        return limpar_resposta(resposta.json()["choices"][0]["message"]["content"] or "")


def limpar_resposta(texto: str) -> str:
    """Tira o bloco <think>…</think> que alguns modelos devolvem junto com a resposta."""
    return re.sub(r"<think>.*?</think>", "", texto, flags=re.S).strip()


def motivo(erro: Exception) -> str:
    """Motivo curto da falha, para o log. Nunca repete a mensagem da API (ela pode citar a chave)."""
    if isinstance(erro, httpx.HTTPStatusError):
        status = erro.response.status_code
        try:
            codigo = erro.response.json()["error"].get("code")
        except Exception:
            codigo = None
        # o OpenRouter manda o código como número; aí traduzimos os mais comuns
        detalhe = codigo if isinstance(codigo, str) else {401: "chave inválida", 402: "sem créditos", 429: "limite de uso atingido"}.get(status, "")
        return f"HTTP {status} {detalhe}".strip()
    return type(erro).__name__


async def responder(pergunta: str, offline: bool) -> str:
    if offline:
        log(AMARELO, "modo offline → resposta montada a partir dos dados")
        return resposta_offline(pergunta)

    log(AZUL, f"→ chamando {MODELO}...")
    inicio = time.monotonic()
    try:
        texto = await perguntar_llm(pergunta)
        if not texto:
            raise ValueError("resposta vazia")
    except Exception as erro:  # rede, timeout, HTTP, resposta vazia: tudo cai no fallback
        log(AMARELO, f"⚠ {MODELO} falhou ({motivo(erro)}) → resposta offline")
        return resposta_offline(pergunta)
    log(AZUL, f"← {MODELO} respondeu em {time.monotonic() - inicio:.1f}s")
    return texto


# ---------- O agente A2A ----------

class SmartRHExecutor(AgentExecutor):
    """Recebe a mensagem e conduz a Task: SUBMITTED → WORKING → Artifact → COMPLETED."""

    def __init__(self, offline: bool) -> None:
        self.offline = offline

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        pergunta = context.get_user_input()
        task_id = context.task_id
        log(NEGRITO, f'← mensagem recebida: "{pergunta}"')

        # 1. Cria a Task
        await event_queue.enqueue_event(
            Task(
                id=task_id,
                context_id=context.context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
                history=[context.message],
            )
        )
        log(VERDE, f"task {task_id[:8]}: SUBMITTED")

        # 2. Começa a trabalhar
        tarefa = TaskUpdater(event_queue, task_id, context.context_id)
        await tarefa.start_work(message=tarefa.new_agent_message([Part(text="consultando dados do time...")]))
        log(VERDE, f"task {task_id[:8]}: WORKING")

        # 3. Entrega o resultado como Artifact e conclui
        texto = await responder(pergunta, self.offline)
        await tarefa.add_artifact([Part(text=texto)], name="perfil-time")
        await tarefa.complete()
        log(VERDE, f"task {task_id[:8]}: COMPLETED")

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()


def montar_card(port: int) -> AgentCard:
    """O "crachá" do agente, servido em /.well-known/agent-card.json."""
    return AgentCard(
        name="Agente Smart RH",
        description="Responde sobre times, headcount e histórico de desligamentos.",
        version="1.0.0",
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", protocol_version="1.0", url=f"http://localhost:{port}/a2a"),
        ],
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=[
            AgentSkill(
                id="perfil-time",
                name="Perfil do time",
                description="Retorna headcount, senioridade e desligamentos recentes de um time.",
                tags=["rh", "times"],
                examples=["Qual o perfil do time de Plataforma?"],
            )
        ],
    )


def criar_app(port: int, offline: bool) -> Starlette:
    card = montar_card(port)
    handler = DefaultRequestHandler(
        agent_executor=SmartRHExecutor(offline),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    return Starlette(routes=create_agent_card_routes(card) + create_jsonrpc_routes(handler, "/a2a"))


# ---------- Subida ----------

def porta_livre(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def verificar_llm() -> bool:
    """Testa chave e modelo antes da demo. Se falhar, a sessão segue offline."""
    if not OPENROUTER_API_KEY:
        log(AMARELO, "⚠ OPENROUTER_API_KEY vazia no .env → modo offline")
        return False
    log(AZUL, f"testando {MODELO} no OpenRouter...")
    inicio = time.monotonic()
    try:
        asyncio.run(perguntar_llm("Responda apenas: ok"))
    except Exception as erro:
        log(AMARELO, f"⚠ {MODELO} indisponível ({motivo(erro)}) → modo offline")
        return False
    log(VERDE, f"{MODELO} ok ({time.monotonic() - inicio:.1f}s)")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agente Smart RH (servidor A2A)")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--offline", action="store_true", help="não chama o LLM; responde só com os dados")
    args = parser.parse_args(argv)

    if not porta_livre(args.port):
        print(f"Porta {args.port} ocupada — já tem um Smart RH rodando? Feche-o ou use --port.")
        return 1

    offline = args.offline or not verificar_llm()
    print(f"\n{NEGRITO}Agente Smart RH no ar{RESET}")
    print(f"  Agent Card: http://localhost:{args.port}/.well-known/agent-card.json")
    print(f"  JSON-RPC:   http://localhost:{args.port}/a2a")
    print(f"  Modelo:     {'offline (dados fictícios)' if offline else MODELO}\n", flush=True)
    uvicorn.run(criar_app(args.port, offline), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
