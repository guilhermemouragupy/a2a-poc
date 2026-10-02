"""Agente Recrutador: o orquestrador.

Lê os crachás dos agentes do catálogo, transforma cada skill numa ferramenta do LLM e
deixa o LLM decidir quem chamar. No fim, pausa a Task em INPUT_REQUIRED para a pessoa
aprovar (ou pedir ajuste) antes de publicar.
"""

import asyncio
import json

from starlette.applications import Starlette

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part

from comum import a2a_cliente, llm, servidor
from comum.eventos import barramento

CATALOGO = ["rh", "remuneracao", "redator"]  # os agentes que o Recrutador conhece
MAX_PASSOS = 6  # guardrail: no máximo 6 voltas no loop de decisão

INSTRUCOES = (
    "Você é o Agente Recrutador. Sua tarefa é preparar o anúncio de uma vaga a partir do pedido da pessoa recrutadora. "
    "Você não tem dados próprios: use as ferramentas, que são outros agentes. "
    "Em geral: consulte o perfil do time e a faixa salarial (pode ser ao mesmo tempo) e depois peça o anúncio ao redator, "
    "passando tudo o que aprendeu. Escreva as mensagens para os agentes em português, de forma objetiva. "
    "Quando o redator entregar o anúncio, responda apenas PRONTO (o anúncio dele já é o resultado)."
)


class LimiteDePassos(Exception):
    """O LLM não entregou o anúncio dentro de MAX_PASSOS."""


def pensar(texto: str) -> None:
    barramento.publicar("pensando", agente="recrutador", texto=texto)


async def descobrir_catalogo() -> dict[str, dict]:
    cards = await asyncio.gather(*(a2a_cliente.descobrir("recrutador", a) for a in CATALOGO))
    return dict(zip(CATALOGO, cards))


def ferramentas(cards: dict[str, dict]) -> tuple[list[dict], dict[str, str]]:
    """Cada skill de cada crachá vira uma ferramenta do LLM. Devolve (ferramentas, skill → agente)."""
    lista, dono = [], {}
    for agente_id, card in cards.items():
        for skill in card["skills"]:
            lista.append({
                "type": "function",
                "function": {
                    "name": skill["id"],
                    "description": f"{card['name']}: {skill['description']}",
                    "parameters": {
                        "type": "object",
                        "properties": {"mensagem": {"type": "string", "description": "O que pedir a esse agente, em português"}},
                        "required": ["mensagem"],
                    },
                },
            })
            dono[skill["id"]] = agente_id
    return lista, dono


async def chamar_ferramenta(chamada: dict, dono: dict[str, str], cards: dict[str, dict]) -> str:
    """Uma decisão do LLM vira uma mensagem A2A para o agente dono da skill."""
    nome = chamada["function"]["name"]
    if nome not in dono:
        return f"Ferramenta desconhecida: {nome}"
    try:
        mensagem = json.loads(chamada["function"]["arguments"])["mensagem"]
    except (json.JSONDecodeError, KeyError, TypeError):
        mensagem = chamada["function"]["arguments"]
    agente_id = dono[nome]
    resultado = await a2a_cliente.enviar("recrutador", agente_id, mensagem, card=cards[agente_id])
    if resultado.estado != a2a_cliente.CONCLUIDA:
        return f"O {cards[agente_id]['name']} não conseguiu responder ({resultado.mensagem})."
    return resultado.texto


async def orquestrar(pedido: str, cards: dict[str, dict]) -> str:
    """Loop de decisão: o LLM escolhe ferramentas (agentes) até entregar o anúncio."""
    lista, dono = ferramentas(cards)
    mensagens = [{"role": "system", "content": INSTRUCOES}, {"role": "user", "content": pedido}]
    ultimo_anuncio = ""
    for passo in range(1, MAX_PASSOS + 1):
        pensar("lendo as skills dos crachás e decidindo quem chamar…" if passo == 1 else f"passo {passo}: decidindo o próximo passo…")
        resposta = await llm.conversar(mensagens, lista)
        chamadas = resposta.get("tool_calls") or []
        if not chamadas:  # o LLM encerrou: vale o anúncio do Redator (sem reescrevê-lo token por token)
            return ultimo_anuncio or (resposta.get("content") or "").strip()
        escolhidos = [cards[dono[c["function"]["name"]]]["name"] if c["function"]["name"] in dono else c["function"]["name"] for c in chamadas]
        pensar("vou chamar: " + ", ".join(escolhidos))
        mensagens.append({"role": "assistant", "content": resposta.get("content"), "tool_calls": chamadas})
        resultados = await asyncio.gather(*(chamar_ferramenta(c, dono, cards) for c in chamadas))
        for chamada, texto in zip(chamadas, resultados):
            mensagens.append({"role": "tool", "tool_call_id": chamada["id"], "content": texto})
            if dono.get(chamada["function"]["name"]) == "redator":
                ultimo_anuncio = texto
    if ultimo_anuncio:
        pensar(f"⚠ limite de {MAX_PASSOS} passos atingido → uso o último anúncio do Redator")
        return ultimo_anuncio
    raise LimiteDePassos(f"{MAX_PASSOS} passos sem anúncio")


async def roteiro_fixo(pedido: str, cards: dict[str, dict]) -> str:
    """Sem LLM: RH e Remuneração ao mesmo tempo, depois o Redator com o que eles responderam."""
    pensar("seguindo o roteiro fixo (sem LLM)")
    perfil, faixa = await asyncio.gather(
        a2a_cliente.enviar("recrutador", "rh", f"Qual o perfil atual do time desta vaga? {pedido}", card=cards["rh"]),
        a2a_cliente.enviar("recrutador", "remuneracao", f"Qual a faixa salarial desta vaga? {pedido}", card=cards["remuneracao"]),
    )
    anuncio = await a2a_cliente.enviar(
        "recrutador",
        "redator",
        f"Escreva o anúncio desta vaga.\nPedido: {pedido}\nPerfil do time: {perfil.texto}\nFaixa salarial: {faixa.texto}",
        card=cards["redator"],
    )
    return anuncio.texto


async def preparar(pedido: str, cards: dict[str, dict]) -> str:
    if not llm.OFFLINE:
        try:
            if anuncio := await orquestrar(pedido, cards):
                return anuncio
        except Exception as erro:
            pensar(f"⚠ orquestração com LLM falhou ({llm.motivo(erro)}) → roteiro fixo")
    return await roteiro_fixo(pedido, cards)


class RecrutadorExecutor(AgentExecutor):
    """Uma Task, duas fases: preparar a vaga (até INPUT_REQUIRED) e, com a resposta humana, publicar ou ajustar."""

    def __init__(self) -> None:
        self.rascunhos: dict[str, str] = {}  # task_id → anúncio aguardando aprovação

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        texto = context.get_user_input()
        nova = context.current_task is None
        tarefa = await servidor.criar_task(context, event_queue) if nova else TaskUpdater(event_queue, context.task_id, context.context_id)
        try:
            if nova:
                await tarefa.start_work(message=servidor.mensagem(tarefa, "lendo os crachás do catálogo…"))
                anuncio = await preparar(texto, await descobrir_catalogo())
            elif texto.strip().lower().startswith("aprovar"):
                await self.publicar(tarefa, context.task_id)
                return
            else:
                anuncio = await self.ajustar(tarefa, context.task_id, texto)
        except Exception as erro:
            await tarefa.failed(message=servidor.mensagem(tarefa, f"falhou: {llm.motivo(erro)}"))
            return
        self.rascunhos[context.task_id] = anuncio
        await tarefa.add_artifact([Part(text=anuncio)], name="rascunho-vaga")
        await tarefa.requires_input(message=servidor.mensagem(tarefa, "A vaga está pronta. Posso publicar?"))

    async def publicar(self, tarefa: TaskUpdater, task_id: str) -> None:
        await tarefa.start_work(message=servidor.mensagem(tarefa, "publicando a vaga…"))
        anuncio = self.rascunhos.pop(task_id, "")
        await tarefa.add_artifact([Part(text=f"✅ Vaga publicada (simulação)\n\n{anuncio}")], name="vaga-publicada")
        await tarefa.complete()

    async def ajustar(self, tarefa: TaskUpdater, task_id: str, pedido_de_ajuste: str) -> str:
        await tarefa.start_work(message=servidor.mensagem(tarefa, "pedindo o ajuste ao Redator…"))
        atual = self.rascunhos.get(task_id, "")
        cards = await descobrir_catalogo()
        resultado = await a2a_cliente.enviar(
            "recrutador",
            "redator",
            f"Ajuste este anúncio. Pedido de ajuste: {pedido_de_ajuste}\n\nAnúncio atual:\n{atual}",
            card=cards["redator"],
        )
        return resultado.texto if resultado.estado == a2a_cliente.CONCLUIDA else atual

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()


def criar_app() -> Starlette:
    card = servidor.criar_card(
        "recrutador",
        descricao="Orquestra a abertura de vagas conversando com outros agentes.",
        skill_id="abrir-vaga",
        skill_nome="Abrir vaga",
        skill_descricao="Prepara o anúncio de uma vaga consultando outros agentes (perfil do time, faixa salarial, redação e compliance) e pede aprovação humana antes de publicar.",
        exemplo="Quero abrir uma vaga de Engenheiro(a) de Software Pleno no time de Plataforma",
    )
    return servidor.criar_app(card, RecrutadorExecutor())
