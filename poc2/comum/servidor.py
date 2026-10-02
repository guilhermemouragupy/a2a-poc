"""Peças para montar um agente A2A com o SDK oficial: crachá, executor simples e app HTTP."""

from collections.abc import Awaitable, Callable

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
    Message,
    Part,
    Task,
    TaskState,
    TaskStatus,
)

from comum import catalogo


def criar_card(agente_id: str, descricao: str, skill_id: str, skill_nome: str, skill_descricao: str, exemplo: str) -> AgentCard:
    """O "crachá" do agente, servido em /.well-known/agent-card.json."""
    info = catalogo.AGENTES[agente_id]
    return AgentCard(
        name=info["nome"],
        description=descricao,
        version="1.0.0",
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", protocol_version="1.0", url=f"{catalogo.url(agente_id)}/a2a"),
        ],
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=[AgentSkill(id=skill_id, name=skill_nome, description=skill_descricao, tags=[agente_id], examples=[exemplo])],
    )


async def criar_task(context: RequestContext, event_queue: EventQueue) -> TaskUpdater:
    """Cria a Task (SUBMITTED) e devolve o TaskUpdater para os próximos estados."""
    await event_queue.enqueue_event(
        Task(
            id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
            history=[context.message],
        )
    )
    return TaskUpdater(event_queue, context.task_id, context.context_id)


def mensagem(tarefa: TaskUpdater, texto: str) -> Message:
    return tarefa.new_agent_message([Part(text=texto)])


class AgenteSimples(AgentExecutor):
    """Agente de uma pergunta e uma resposta: SUBMITTED → WORKING → Artifact → COMPLETED."""

    def __init__(self, nome_artifact: str, trabalhando: str, responder: Callable[[str], Awaitable[str]]) -> None:
        self.nome_artifact = nome_artifact
        self.trabalhando = trabalhando
        self.responder = responder

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        tarefa = await criar_task(context, event_queue)
        await tarefa.start_work(message=mensagem(tarefa, self.trabalhando))
        try:
            texto = await self.responder(context.get_user_input())
        except Exception as erro:
            await tarefa.failed(message=mensagem(tarefa, f"falhou: {type(erro).__name__}"))
            return
        await tarefa.add_artifact([Part(text=texto)], name=self.nome_artifact)
        await tarefa.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()


def criar_app(card: AgentCard, executor: AgentExecutor) -> Starlette:
    handler = DefaultRequestHandler(agent_executor=executor, task_store=InMemoryTaskStore(), agent_card=card)
    return Starlette(routes=create_agent_card_routes(card) + create_jsonrpc_routes(handler, "/a2a"))
