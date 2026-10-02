"""Sobe a POC 2 inteira (modo offline, portas livres) numa thread, uma vez para todos os testes."""

import asyncio
import socket
import threading
import time

import pytest

import rodar
from comum import catalogo, llm


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _esperar_porta(porta: int, limite: float = 10.0) -> None:
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", porta)) == 0:
                return
        time.sleep(0.1)
    raise RuntimeError(f"porta {porta} não abriu")


@pytest.fixture(scope="session")
def sistema():
    llm.OFFLINE = True
    for info in catalogo.AGENTES.values():
        info["porta"] = porta_livre()
    catalogo.PORTA_PAINEL = porta_livre()
    servidores = rodar.montar_servidores()
    thread = threading.Thread(target=lambda: asyncio.run(rodar.servir(servidores)), daemon=True)
    thread.start()
    for porta in [i["porta"] for i in catalogo.AGENTES.values()] + [catalogo.PORTA_PAINEL]:
        _esperar_porta(porta)
    yield f"http://localhost:{catalogo.PORTA_PAINEL}"
    for servidor in servidores:
        servidor.should_exit = True
    thread.join(timeout=5)
