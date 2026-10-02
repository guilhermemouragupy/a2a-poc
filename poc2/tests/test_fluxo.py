"""Fluxo A2A de verdade (HTTP entre as portas), em modo offline."""

import asyncio

from comum import a2a_cliente
from comum.eventos import barramento

PEDIDO = "Quero abrir uma vaga de Engenheiro(a) de Software Pleno no time de Plataforma"


def pares_de_mensagens(desde: int) -> list[tuple[str, str]]:
    return [(e["de"], e["para"]) for e in barramento.historico[desde:] if e["tipo"] == "mensagem"]


def test_cards_publicados(sistema):
    async def ler():
        return {a: await a2a_cliente.descobrir("teste", a) for a in ["recrutador", "rh", "remuneracao", "redator", "compliance"]}

    cards = asyncio.run(ler())
    skills = {a: card["skills"][0]["id"] for a, card in cards.items()}
    assert skills == {
        "recrutador": "abrir-vaga",
        "rh": "perfil-time",
        "remuneracao": "faixa-salarial",
        "redator": "escrever-vaga",
        "compliance": "revisar-vaga",
    }


def test_fluxo_completo_ate_publicar(sistema):
    inicio = len(barramento.historico)

    async def fluxo():
        card = await a2a_cliente.descobrir("voce", "recrutador")
        pausa = await a2a_cliente.enviar("voce", "recrutador", PEDIDO, card=card)
        final = await a2a_cliente.enviar(
            "voce", "recrutador", "aprovar", card=card, task_id=pausa.task_id, context_id=pausa.context_id
        )
        return pausa, final

    pausa, final = asyncio.run(fluxo())
    assert pausa.estado == a2a_cliente.PRECISA_DE_INPUT
    assert pausa.mensagem == "A vaga está pronta. Posso publicar?"
    assert "12 pessoas" in pausa.artifacts["rascunho-vaga"]
    assert final.estado == a2a_cliente.CONCLUIDA
    assert "Vaga publicada" in final.artifacts["vaga-publicada"]
    pares = pares_de_mensagens(inicio)
    for par in [("recrutador", "rh"), ("recrutador", "remuneracao"), ("recrutador", "redator"), ("redator", "compliance")]:
        assert par in pares


def test_pedir_ajuste_gera_nova_aprovacao(sistema):
    async def fluxo():
        card = await a2a_cliente.descobrir("voce", "recrutador")
        pausa = await a2a_cliente.enviar("voce", "recrutador", PEDIDO, card=card)
        meio = len(barramento.historico)
        ajuste = await a2a_cliente.enviar(
            "voce", "recrutador", "Deixe claro que o trabalho é remoto",
            card=card, task_id=pausa.task_id, context_id=pausa.context_id,
        )
        return pausa, ajuste, meio

    pausa, ajuste, meio = asyncio.run(fluxo())
    assert ajuste.estado == a2a_cliente.PRECISA_DE_INPUT
    assert ajuste.task_id == pausa.task_id
    assert "remoto" in ajuste.artifacts["rascunho-vaga"]
    assert ("recrutador", "redator") in pares_de_mensagens(meio)
    assert ("redator", "compliance") in pares_de_mensagens(meio)
