"""Agente Smart Vagas — cliente A2A SEM SDK: só HTTP + JSON (httpx).

Mostra os 4 passos do protocolo: descobrir (Agent Card), delegar
(SendStreamingMessage), acompanhar (eventos da Task via SSE) e receber o Artifact.

Uso:  python smart_vagas.py [pergunta] [--direto] [--url http://localhost:9999]
      Sem pergunta, o programa pergunta a você, uma de cada vez, até Enter vazio.
"""

import argparse
import json
import sys
import time
import uuid

import httpx

AZUL, VERDE, AMARELO, VERMELHO, CINZA, NEGRITO, RESET = (
    "\033[34m", "\033[32m", "\033[33m", "\033[31m", "\033[90m", "\033[1m", "\033[0m",
)


class ErroA2A(Exception):
    """Erro devolvido pelo agente remoto no envelope JSON-RPC."""


def passo(numero: int, titulo: str, detalhe: str) -> None:
    print(f"\n{NEGRITO}{AZUL}{numero}. {titulo}{RESET}  {CINZA}{detalhe}{RESET}")


def mostrar_json(dados: dict) -> None:
    print(CINZA + json.dumps(dados, indent=2, ensure_ascii=False) + RESET)


def pausar(direto: bool, acao: str = "continuar") -> None:
    if not direto:
        input(f"{CINZA}[Enter para {acao}]{RESET}")


def _estado(estado: str) -> str:
    nome = estado.removeprefix("TASK_STATE_")
    cor = {"COMPLETED": VERDE, "FAILED": VERMELHO}.get(nome, AMARELO)
    return f"{cor}{nome:<10}{RESET}"


def _texto(parts: list[dict]) -> str:
    return "".join(p.get("text", "") for p in parts)


def descobrir(client: httpx.Client, url_base: str) -> str:
    """Passo 1: lê o Agent Card e devolve a URL do endpoint JSON-RPC."""
    resposta = client.get(f"{url_base}/.well-known/agent-card.json")
    resposta.raise_for_status()
    card = resposta.json()
    mostrar_json(card)
    rpc_url = next(i["url"] for i in card["supportedInterfaces"] if i["protocolBinding"] == "JSONRPC")
    skills = ", ".join(s["id"] for s in card["skills"])
    print(f"{VERDE}→ encontrei: {card['name']} · skills: {skills} · JSON-RPC em {rpc_url}{RESET}")
    return rpc_url


def montar_requisicao(pergunta: str) -> dict:
    """Passo 2: a mensagem, embrulhada num pedido JSON-RPC."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendStreamingMessage",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "ROLE_USER",
                "parts": [{"text": pergunta}],
            }
        },
    }


def acompanhar(client: httpx.Client, rpc_url: str, requisicao: dict) -> tuple[str, str]:
    """Passo 3: envia e lê o stream SSE. Devolve (estado final, texto do artifact)."""
    estado, artefato = "", ""
    inicio = time.monotonic()
    with client.stream("POST", rpc_url, json=requisicao, headers={"A2A-Version": "1.0"}) as resposta:
        if not resposta.headers.get("content-type", "").startswith("text/event-stream"):
            erro = json.loads(resposta.read()).get("error", {})
            raise ErroA2A(erro.get("message", f"HTTP {resposta.status_code}"))

        for linha in resposta.iter_lines():
            if not linha.startswith("data:"):
                continue
            evento = json.loads(linha.removeprefix("data:"))
            if "error" in evento:
                raise ErroA2A(evento["error"].get("message"))

            resultado = evento["result"]
            t = f"{CINZA}+{time.monotonic() - inicio:4.1f}s{RESET}"
            if "task" in resultado:
                task = resultado["task"]
                estado = task["status"]["state"]
                print(f"  {t}  task            {_estado(estado)} id={task['id'][:8]}")
            elif "statusUpdate" in resultado:
                status = resultado["statusUpdate"]["status"]
                estado = status["state"]
                mensagem = _texto(status.get("message", {}).get("parts", []))
                print(f"  {t}  statusUpdate    {_estado(estado)} {CINZA}{mensagem}{RESET}")
            elif "artifactUpdate" in resultado:
                artifact = resultado["artifactUpdate"]["artifact"]
                artefato += _texto(artifact["parts"])
                print(f"  {t}  artifactUpdate  {artifact.get('name', '')}")
    return estado, artefato


def ler_pergunta() -> str:
    try:
        return input(f"\n{NEGRITO}Pergunta para o Smart RH{RESET} {CINZA}(Enter vazio para sair){RESET}: ").strip()
    except EOFError:
        return ""


def conversar(client: httpx.Client, rpc_url: str, pergunta: str, direto: bool) -> bool:
    """Passos 2 a 4 para uma pergunta. Devolve True se a Task terminou em COMPLETED."""
    requisicao = montar_requisicao(pergunta)
    passo(2, "DELEGAR", f"POST {rpc_url}   header A2A-Version: 1.0")
    mostrar_json(requisicao)
    pausar(direto, "enviar")

    passo(3, "ACOMPANHAR", "eventos da Task via streaming (SSE)")
    estado, artefato = acompanhar(client, rpc_url, requisicao)
    pausar(direto)

    passo(4, "ARTIFACT", "o resultado entregue pelo Smart RH")
    print(f"{NEGRITO}{artefato}{RESET}")
    return estado == "TASK_STATE_COMPLETED"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agente Smart Vagas (cliente A2A)")
    parser.add_argument("pergunta", nargs="*", help="pergunta para o Smart RH; sem ela, o programa pergunta a você")
    parser.add_argument("--direto", action="store_true", help="roda sem pausas")
    parser.add_argument("--url", default="http://localhost:9999", help="endereço do Agente Smart RH")
    args = parser.parse_args(argv)
    pergunta = " ".join(args.pergunta).strip()
    interativo = not pergunta

    print(f"{NEGRITO}Agente Smart Vagas{RESET}")
    tudo_ok = True
    try:
        with httpx.Client(timeout=httpx.Timeout(60, connect=5)) as client:
            passo(1, "DESCOBRIR", f"GET {args.url}/.well-known/agent-card.json")
            rpc_url = descobrir(client, args.url)

            if not interativo:
                pausar(args.direto)
                return 0 if conversar(client, rpc_url, pergunta, args.direto) else 1

            while pergunta := ler_pergunta():
                tudo_ok = conversar(client, rpc_url, pergunta, args.direto) and tudo_ok
    except httpx.ConnectError:
        print(f"{VERMELHO}Não achei o Agente Smart RH em {args.url}. "
              f"Suba o Smart RH primeiro: python smart_rh.py{RESET}")
        return 1
    except (httpx.HTTPError, ErroA2A) as erro:
        print(f"{VERMELHO}Erro falando com o Smart RH: {erro}{RESET}")
        return 1
    except KeyboardInterrupt:
        print()
        return 130
    return 0 if tudo_ok else 1


if __name__ == "__main__":
    sys.exit(main())
