"""Painel: a interface web. Mostra a conversa entre os agentes e é o "cliente" da pessoa recrutadora."""

import asyncio
import json
from pathlib import Path

import httpx
from sse_starlette import EventSourceResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from comum import a2a_cliente, catalogo, llm
from comum.eventos import barramento

PAGINA = Path(__file__).parent / "index.html"
conversa = {"ocupado": False, "task_id": "", "context_id": ""}  # uma conversa por vez
_tarefas: set[asyncio.Task] = set()


def _em_segundo_plano(corotina) -> None:
    tarefa = asyncio.create_task(corotina)
    _tarefas.add(tarefa)
    tarefa.add_done_callback(_tarefas.discard)


async def falar_com_recrutador(texto: str, task_id: str = "", context_id: str = "") -> None:
    """O Painel é o cliente A2A da pessoa: manda o pedido (ou a resposta) ao Recrutador."""
    try:
        card = await a2a_cliente.descobrir("voce", "recrutador")
        r = await a2a_cliente.enviar("voce", "recrutador", texto, card=card, task_id=task_id, context_id=context_id)
        if r.estado == a2a_cliente.PRECISA_DE_INPUT:
            conversa.update(task_id=r.task_id, context_id=r.context_id)
            barramento.publicar("aprovacao", task_id=r.task_id, pergunta=r.mensagem, texto=r.artifacts.get("rascunho-vaga", r.texto))
        else:
            conversa.update(task_id="", context_id="")
            barramento.publicar("fim", estado=r.estado, texto=r.texto)
    except Exception as erro:
        conversa.update(task_id="", context_id="")
        barramento.publicar("erro", agente="recrutador", texto=f"Painel → Recrutador: {llm.motivo(erro)}")
        barramento.publicar("fim", estado=a2a_cliente.FALHOU, texto="")
    finally:
        conversa["ocupado"] = False


async def pagina(request: Request) -> FileResponse:
    return FileResponse(PAGINA)


async def agentes(request: Request) -> JSONResponse:
    async with httpx.AsyncClient(timeout=5) as client:
        respostas = await asyncio.gather(
            *(client.get(f"{catalogo.url(a)}/.well-known/agent-card.json") for a in catalogo.AGENTES),
            return_exceptions=True,
        )
    lista = [{"id": "voce", "nome": "Você", "emoji": "🧑‍💼", "card": None}]
    for (agente_id, info), resposta in zip(catalogo.AGENTES.items(), respostas):
        card = resposta.json() if isinstance(resposta, httpx.Response) and resposta.status_code == 200 else None
        lista.append({"id": agente_id, "nome": info["nome"], "emoji": info["emoji"], "card": card})
    return JSONResponse({"agentes": lista, "modelo": "offline" if llm.OFFLINE else llm.MODELO})


async def pedido(request: Request) -> JSONResponse:
    texto = ((await request.json()).get("texto") or "").strip()
    if not texto:
        return JSONResponse({"erro": "pedido vazio"}, status_code=400)
    if conversa["ocupado"]:
        return JSONResponse({"erro": "já tem uma conversa em andamento"}, status_code=409)
    conversa.update(ocupado=True, task_id="", context_id="")
    barramento.limpar()
    a2a_cliente.esquecer_cards()  # a descoberta aparece de novo a cada conversa
    barramento.publicar("inicio", texto=texto)
    _em_segundo_plano(falar_com_recrutador(texto))
    return JSONResponse({"ok": True})


async def resposta(request: Request) -> JSONResponse:
    texto = ((await request.json()).get("texto") or "").strip()
    if not conversa["task_id"]:
        return JSONResponse({"erro": "nenhuma vaga aguardando aprovação"}, status_code=409)
    if not texto:
        return JSONResponse({"erro": "resposta vazia"}, status_code=400)
    if conversa["ocupado"]:
        return JSONResponse({"erro": "o Recrutador ainda está trabalhando"}, status_code=409)
    conversa["ocupado"] = True
    _em_segundo_plano(falar_com_recrutador(texto, conversa["task_id"], conversa["context_id"]))
    return JSONResponse({"ok": True})


async def historico(request: Request) -> JSONResponse:
    return JSONResponse({"eventos": barramento.historico})


async def eventos(request: Request) -> EventSourceResponse:
    fila = barramento.assinar()

    async def gerar():
        try:
            while True:
                evento = await fila.get()
                yield {"data": json.dumps(evento, ensure_ascii=False, default=str)}
        finally:
            barramento.cancelar(fila)

    return EventSourceResponse(gerar())


def criar_app() -> Starlette:
    return Starlette(routes=[
        Route("/", pagina),
        Route("/agentes", agentes),
        Route("/eventos", eventos),
        Route("/historico", historico),
        Route("/pedido", pedido, methods=["POST"]),
        Route("/resposta", resposta, methods=["POST"]),
    ])
