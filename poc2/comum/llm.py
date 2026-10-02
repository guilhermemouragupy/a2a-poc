"""O LLM dos agentes: OpenRouter (chave em poc2/.env), com fallback offline."""

import asyncio
import os
import re
import ssl
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
import truststore
from dotenv import load_dotenv

from comum.eventos import barramento

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELO_PADRAO = "z-ai/glm-5.3-flash"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
MODELO = os.environ.get("OPENROUTER_MODEL") or MODELO_PADRAO
TIMEOUT_LLM = 20  # segundos; passou disso, o agente usa a resposta offline
# Certificados do sistema (keychain do macOS): a rede corporativa inspeciona TLS com CA própria.
SSL_SISTEMA = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

OFFLINE = False  # ligado pelo rodar.py (--offline, ou quando a verificação inicial falha)

# Quando o provedor está congestionado ele responde 429/502/503; uma nova tentativa logo depois
# costuma funcionar. Esperas (s) entre as tentativas:
ESPERAS = (0.7, 1.5, 3.0)
REPETIR = {429, 502, 503}


async def com_novas_tentativas(chamada: Callable[[], Awaitable[httpx.Response]], esperas=ESPERAS) -> httpx.Response:
    """Faz a chamada e, se o provedor estiver congestionado, tenta de novo algumas vezes."""
    for espera in (*esperas, None):
        resposta = await chamada()
        if resposta.status_code not in REPETIR or espera is None:
            return resposta
        await asyncio.sleep(espera)


async def conversar(mensagens: list[dict], ferramentas: list[dict] | None = None) -> dict:
    """Uma chamada ao chat do OpenRouter (formato OpenAI). Devolve a mensagem do assistente."""
    if OFFLINE:
        raise RuntimeError("modo offline")
    # o GLM não deixa desligar o raciocínio; o esforço mínimo responde em <1s
    corpo = {"model": MODELO, "messages": mensagens, "reasoning": {"effort": "minimal"}}
    if ferramentas:
        corpo["tools"] = ferramentas
    async with httpx.AsyncClient(timeout=TIMEOUT_LLM, verify=SSL_SISTEMA) as client:
        resposta = await com_novas_tentativas(lambda: client.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "X-Title": "POC 2 A2A"},
            json=corpo,
        ))
        resposta.raise_for_status()
        return resposta.json()["choices"][0]["message"]


async def completar(instrucoes: str, pergunta: str) -> str:
    mensagem = await conversar([{"role": "system", "content": instrucoes}, {"role": "user", "content": pergunta}])
    # alguns modelos devolvem o raciocínio num bloco <think>…</think>
    texto = re.sub(r"<think>.*?</think>", "", mensagem.get("content") or "", flags=re.S).strip()
    if not texto:
        raise ValueError("resposta vazia")
    return texto


async def responder(agente: str, instrucoes: str, pergunta: str, offline: Callable[[], str]) -> str:
    """Resposta do agente pelo LLM; se não der, a resposta offline (e o Painel fica sabendo)."""
    if OFFLINE:
        return offline()
    barramento.publicar("pensando", agente=agente, texto=f"consultando {MODELO}…")
    try:
        return await completar(instrucoes, pergunta)
    except Exception as erro:  # rede, timeout, HTTP, resposta vazia: tudo cai no fallback
        barramento.publicar("pensando", agente=agente, texto=f"⚠ LLM falhou ({motivo(erro)}) → resposta offline")
        return offline()


def motivo(erro: Exception) -> str:
    """Motivo curto de uma falha. Nunca repete a mensagem da API (ela pode citar a chave)."""
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


async def verificar() -> str | None:
    """Testa chave e modelo antes da demo. Devolve None se estiver tudo certo, ou o motivo da falha."""
    if not OPENROUTER_API_KEY:
        return "OPENROUTER_API_KEY vazia no .env"
    try:
        await completar("Responda apenas: ok", "ok")
    except Exception as erro:
        return motivo(erro)
    return None
