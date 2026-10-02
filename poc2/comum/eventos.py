"""Barramento de eventos em memória: os agentes publicam o que fazem, o Painel repassa ao navegador."""

import asyncio
import threading
import time


class Barramento:
    def __init__(self) -> None:
        self.historico: list[dict] = []
        self._assinantes: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._trava = threading.Lock()

    def publicar(self, tipo: str, **dados) -> None:
        evento = {"tipo": tipo, "ts": time.time(), **dados}
        with self._trava:
            self.historico.append(evento)
            assinantes = list(self._assinantes)
        for loop, fila in assinantes:
            try:  # o assinante pode estar noutro loop/thread
                loop.call_soon_threadsafe(fila.put_nowait, evento)
            except RuntimeError:  # loop já fechado
                self.cancelar(fila)

    def assinar(self) -> asyncio.Queue:
        fila: asyncio.Queue = asyncio.Queue()
        with self._trava:
            self._assinantes.append((asyncio.get_running_loop(), fila))
        return fila

    def cancelar(self, fila: asyncio.Queue) -> None:
        with self._trava:
            self._assinantes = [(loop, f) for loop, f in self._assinantes if f is not fila]

    def limpar(self) -> None:
        with self._trava:
            self.historico.clear()


barramento = Barramento()
