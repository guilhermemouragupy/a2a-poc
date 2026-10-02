import asyncio

import pytest

from agentes import compliance, recrutador, redator, remuneracao, smart_rh
from comum import a2a_cliente


def test_rh_offline():
    assert "12 pessoas" in smart_rh.resposta_offline("perfil do time de plataforma")


def test_remuneracao_offline_com_cargo_e_nivel():
    assert "R$ 11–15 mil" in remuneracao.resposta_offline("Engenheiro(a) de Software Pleno")


def test_remuneracao_offline_so_com_area():
    texto = remuneracao.resposta_offline("vaga no time de Dados")
    assert "júnior" in texto
    assert "sênior" in texto


def test_compliance_offline_aponta_termos_discriminatorios():
    parecer = compliance.revisao_offline("Buscamos pessoa jovem e com boa aparência")
    assert parecer.startswith("AJUSTES:")
    assert "jovem" in parecer


def test_compliance_offline_aprova_rascunho_do_redator():
    # o rascunho diz "diversidade", que contém "idade": não pode ser falso positivo
    assert compliance.revisao_offline(redator.rascunho_offline("Vaga de Analista de Dados")).startswith("APROVADO")


def test_redator_offline_monta_o_anuncio_com_os_dados_recebidos():
    pedido = "Escreva o anúncio desta vaga.\nPedido: Vaga X\nPerfil do time: 12 pessoas\nFaixa salarial: R$ 11–15 mil"
    anuncio = redator.rascunho_offline(pedido)
    assert "Sobre o time: 12 pessoas" in anuncio
    assert "Remuneração: R$ 11–15 mil" in anuncio
    assert "Contexto recebido" not in anuncio


def test_redator_offline_aplica_o_ajuste_pedido():
    pedido = "Ajuste este anúncio. Pedido de ajuste: é remoto\n\nAnúncio atual:\nTEXTO DA VAGA\n\n[Compliance] APROVADO"
    assert redator.rascunho_offline(pedido) == "TEXTO DA VAGA\nAjuste aplicado: é remoto"


CARDS = {
    "rh": {"name": "Agente Smart RH", "skills": [{"id": "perfil-time", "description": "perfil do time"}]},
    "remuneracao": {"name": "Agente de Remuneração", "skills": [{"id": "faixa-salarial", "description": "faixa"}]},
    "redator": {"name": "Agente Redator", "skills": [{"id": "escrever-vaga", "description": "escreve"}]},
}


def test_ferramentas_vem_das_skills_dos_crachas():
    lista, dono = recrutador.ferramentas(CARDS)
    assert [f["function"]["name"] for f in lista] == ["perfil-time", "faixa-salarial", "escrever-vaga"]
    assert dono == {"perfil-time": "rh", "faixa-salarial": "remuneracao", "escrever-vaga": "redator"}
    assert lista[0]["function"]["description"].startswith("Agente Smart RH")


def _chamada(i: int, nome: str) -> dict:
    return {"id": f"c{i}", "type": "function", "function": {"name": nome, "arguments": '{"mensagem": "oi"}'}}


@pytest.fixture
def agentes_falsos(monkeypatch):
    chamados = []

    async def enviar(de, para, texto, *, card, task_id="", context_id=""):
        chamados.append(para)
        return a2a_cliente.Resultado(estado=a2a_cliente.CONCLUIDA, artifacts={"r": f"resposta de {para}"})

    monkeypatch.setattr(a2a_cliente, "enviar", enviar)
    return chamados


def test_orquestrar_segue_as_decisoes_do_llm(monkeypatch, agentes_falsos):
    respostas = iter([
        {"content": None, "tool_calls": [_chamada(1, "perfil-time"), _chamada(2, "faixa-salarial")]},
        {"content": None, "tool_calls": [_chamada(3, "escrever-vaga")]},
        {"content": "PRONTO"},
    ])

    async def conversar(mensagens, ferramentas=None):
        return next(respostas)

    monkeypatch.setattr(recrutador.llm, "conversar", conversar)
    # o LLM só diz "PRONTO"; o anúncio é o que o Redator entregou (sem reescrever token por token)
    assert asyncio.run(recrutador.orquestrar("abrir vaga", CARDS)) == "resposta de redator"
    assert sorted(agentes_falsos[:2]) == ["remuneracao", "rh"]
    assert agentes_falsos[2:] == ["redator"]


def test_orquestrar_respeita_max_passos(monkeypatch, agentes_falsos):
    async def conversar(mensagens, ferramentas=None):
        return {"content": None, "tool_calls": [_chamada(len(mensagens), "perfil-time")]}

    monkeypatch.setattr(recrutador.llm, "conversar", conversar)
    with pytest.raises(recrutador.LimiteDePassos):
        asyncio.run(recrutador.orquestrar("abrir vaga", CARDS))
    assert len(agentes_falsos) == recrutador.MAX_PASSOS


def test_orquestrar_no_limite_usa_o_ultimo_anuncio(monkeypatch, agentes_falsos):
    async def conversar(mensagens, ferramentas=None):
        return {"content": None, "tool_calls": [_chamada(len(mensagens), "escrever-vaga")]}

    monkeypatch.setattr(recrutador.llm, "conversar", conversar)
    assert asyncio.run(recrutador.orquestrar("abrir vaga", CARDS)) == "resposta de redator"


def test_orquestrar_sem_redator_usa_a_resposta_do_llm(monkeypatch, agentes_falsos):
    async def conversar(mensagens, ferramentas=None):
        return {"content": "Não consigo abrir essa vaga sem saber o time."}

    monkeypatch.setattr(recrutador.llm, "conversar", conversar)
    assert asyncio.run(recrutador.orquestrar("abrir vaga", CARDS)) == "Não consigo abrir essa vaga sem saber o time."
