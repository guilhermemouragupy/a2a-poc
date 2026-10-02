"""Sobe os 5 agentes A2A e o Painel com um comando.

Uso:  python rodar.py [--offline]
"""

import argparse
import asyncio
import contextlib
import socket
import sys

import uvicorn

from agentes import compliance, recrutador, redator, remuneracao, smart_rh
from comum import catalogo, llm
from comum.eventos import barramento
from painel import app as painel

MODULOS = {"recrutador": recrutador, "rh": smart_rh, "remuneracao": remuneracao, "redator": redator, "compliance": compliance}


class Servidor(uvicorn.Server):
    @contextlib.contextmanager
    def capture_signals(self):  # o Ctrl+C é tratado uma vez só, para todos os servidores
        yield


def montar_servidores() -> list[Servidor]:
    apps = [(MODULOS[a].criar_app(), info["porta"]) for a, info in catalogo.AGENTES.items()]
    apps.append((painel.criar_app(), catalogo.PORTA_PAINEL))
    return [Servidor(uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="warning")) for app, porta in apps]


async def servir(servidores: list[Servidor]) -> None:
    await asyncio.gather(*(s.serve() for s in servidores))


def portas_ocupadas() -> list[int]:
    portas = [info["porta"] for info in catalogo.AGENTES.values()] + [catalogo.PORTA_PAINEL]
    ocupadas = []
    for porta in portas:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", porta)) == 0:
                ocupadas.append(porta)
    return ocupadas


async def espelhar_no_terminal() -> None:
    """Resumo de cada evento no terminal, para quem estiver olhando o log."""
    fila = barramento.assinar()
    while True:
        e = await fila.get()
        if e["tipo"] == "mensagem":
            print(f"  {e['de']:>11} → {e['para']:<11} {e['texto'][:70]!r}", flush=True)
        elif e["tipo"] == "estado":
            print(f"  {e['agente']:>11}   {e['estado'].removeprefix('TASK_STATE_')}", flush=True)
        elif e["tipo"] == "artifact":
            print(f"  {e['de']:>11} → {e['para']:<11} 📦 {e['nome']}", flush=True)
        elif e["tipo"] in ("pensando", "erro"):
            print(f"  {e['agente']:>11}   {e['texto']}", flush=True)


def banner() -> None:
    modo = "offline (respostas montadas dos dados fictícios)" if llm.OFFLINE else llm.MODELO
    print(f"\nPOC 2 A2A no ar — LLM: {modo}")
    print(f"  Painel: http://localhost:{catalogo.PORTA_PAINEL}   ← abra no navegador")
    for info in catalogo.AGENTES.values():
        print(f"  {info['emoji']}  {info['nome']:<22} http://localhost:{info['porta']}/.well-known/agent-card.json")
    print("Ctrl+C para encerrar.\n", flush=True)


async def principal(offline: bool) -> int:
    if ocupadas := portas_ocupadas():
        print(f"Portas ocupadas: {ocupadas} — já tem uma POC 2 rodando? Feche-a (Ctrl+C) e tente de novo.")
        return 1
    if offline:
        llm.OFFLINE = True
    elif problema := await llm.verificar():
        print(f"⚠ {llm.MODELO} indisponível ({problema}) → modo offline")
        llm.OFFLINE = True
    banner()
    espelho = asyncio.create_task(espelhar_no_terminal())
    await servir(montar_servidores())
    espelho.cancel()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="POC 2 A2A: 5 agentes + Painel")
    parser.add_argument("--offline", action="store_true", help="não chama o LLM; respostas montadas dos dados")
    args = parser.parse_args(argv)
    try:
        return asyncio.run(principal(args.offline))
    except KeyboardInterrupt:
        print("\nPOC 2 encerrada.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
