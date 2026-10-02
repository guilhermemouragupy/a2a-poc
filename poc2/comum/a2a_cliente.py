"""Cliente A2A sem SDK (só HTTP + JSON), usado para um agente falar com outro.

Tudo o que ele envia e recebe também vai para o barramento — é isso que o Painel mostra.
"""

import json
import uuid
from dataclasses import dataclass, field

import httpx

from comum import catalogo, llm
from comum.eventos import barramento

TIMEOUT_A2A = httpx.Timeout(120, connect=5)
CONCLUIDA = "TASK_STATE_COMPLETED"
PRECISA_DE_INPUT = "TASK_STATE_INPUT_REQUIRED"
FALHOU = "TASK_STATE_FAILED"

_cards: dict[tuple[str, str], dict] = {}


@dataclass
class Resultado:
    estado: str = ""
    task_id: str = ""
    context_id: str = ""
    mensagem: str = ""  # última mensagem de status do agente remoto
    artifacts: dict[str, str] = field(default_factory=dict)

    @property
    def texto(self) -> str:
        return "\n\n".join(self.artifacts.values()) or self.mensagem


class ErroA2A(Exception):
    """Erro devolvido pelo agente remoto no envelope JSON-RPC."""


def esquecer_cards() -> None:
    """Esquece os crachás lidos (para a descoberta aparecer de novo numa nova conversa)."""
    _cards.clear()


async def descobrir(de: str, para: str) -> dict:
    """Lê o Agent Card de um agente do catálogo (uma vez por par de agentes)."""
    if (de, para) not in _cards:
        async with httpx.AsyncClient(timeout=10) as client:
            resposta = await client.get(f"{catalogo.url(para)}/.well-known/agent-card.json")
            resposta.raise_for_status()
        _cards[(de, para)] = resposta.json()
        barramento.publicar("descoberta", de=de, para=para, card=_cards[(de, para)])
    return _cards[(de, para)]


def _texto(parts: list[dict]) -> str:
    return "".join(p.get("text", "") for p in parts)


def _registrar(resultado: dict, de: str, para: str, res: Resultado) -> None:
    """Atualiza o Resultado com um evento do stream e avisa o Painel."""
    if "task" in resultado:
        task = resultado["task"]
        res.task_id, res.context_id, res.estado = task["id"], task["contextId"], task["status"]["state"]
        barramento.publicar("estado", agente=para, task_id=res.task_id, estado=res.estado, texto="", bruto=resultado)
    elif "statusUpdate" in resultado:
        atualizacao = resultado["statusUpdate"]
        res.task_id = res.task_id or atualizacao["taskId"]
        res.context_id = res.context_id or atualizacao["contextId"]
        res.estado = atualizacao["status"]["state"]
        texto = _texto(atualizacao["status"].get("message", {}).get("parts", []))
        res.mensagem = texto or res.mensagem
        barramento.publicar("estado", agente=para, task_id=res.task_id, estado=res.estado, texto=texto, bruto=resultado)
    elif "artifactUpdate" in resultado:
        artifact = resultado["artifactUpdate"]["artifact"]
        nome, texto = artifact.get("name", "resultado"), _texto(artifact["parts"])
        res.artifacts[nome] = texto
        barramento.publicar("artifact", de=para, para=de, nome=nome, texto=texto, bruto=resultado)


async def enviar(de: str, para: str, texto: str, *, card: dict, task_id: str = "", context_id: str = "") -> Resultado:
    """Envia uma mensagem A2A (SendStreamingMessage) e acompanha a Task até ela terminar ou pausar.

    Nunca levanta exceção: se algo der errado, devolve um Resultado com estado FAILED.
    """
    rpc_url = next(i["url"] for i in card["supportedInterfaces"] if i["protocolBinding"] == "JSONRPC")
    mensagem = {"messageId": str(uuid.uuid4()), "role": "ROLE_USER", "parts": [{"text": texto}]}
    if task_id:  # continua uma Task que estava pausada
        mensagem |= {"taskId": task_id, "contextId": context_id}
    requisicao = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "SendStreamingMessage", "params": {"message": mensagem}}
    barramento.publicar("mensagem", de=de, para=para, texto=texto, task_id=task_id, bruto=requisicao)

    res = Resultado(task_id=task_id, context_id=context_id)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_A2A) as client:
            async with client.stream("POST", rpc_url, json=requisicao, headers={"A2A-Version": "1.0"}) as resposta:
                if not resposta.headers.get("content-type", "").startswith("text/event-stream"):
                    erro = json.loads(await resposta.aread()).get("error", {})
                    raise ErroA2A(erro.get("message", f"HTTP {resposta.status_code}"))
                async for linha in resposta.aiter_lines():
                    if not linha.startswith("data:"):
                        continue
                    evento = json.loads(linha.removeprefix("data:"))
                    if "error" in evento:
                        raise ErroA2A(evento["error"].get("message"))
                    _registrar(evento["result"], de, para, res)
    except Exception as erro:
        res.estado, res.mensagem = FALHOU, llm.motivo(erro)
        barramento.publicar("erro", agente=para, texto=f"{de} → {para}: {res.mensagem}")
    return res
