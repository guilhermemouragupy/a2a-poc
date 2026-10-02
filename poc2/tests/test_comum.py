import asyncio
import threading

import httpx
import pytest

from comum import catalogo, llm
from comum.eventos import barramento


def test_catalogo_monta_url():
    assert catalogo.url("rh") == f"http://localhost:{catalogo.AGENTES['rh']['porta']}"


def test_barramento_guarda_historico_e_entrega_ao_assinante():
    async def cenario():
        fila = barramento.assinar()
        barramento.publicar("teste", valor=1)
        evento = await asyncio.wait_for(fila.get(), 1)
        barramento.cancelar(fila)
        return evento

    evento = asyncio.run(cenario())
    assert evento["tipo"] == "teste"
    assert evento["valor"] == 1
    assert barramento.historico[-1] is evento


def test_barramento_entrega_eventos_publicados_de_outra_thread():
    async def cenario():
        fila = barramento.assinar()
        threading.Thread(target=lambda: barramento.publicar("de-outra-thread")).start()
        evento = await asyncio.wait_for(fila.get(), 1)
        barramento.cancelar(fila)
        return evento

    assert asyncio.run(cenario())["tipo"] == "de-outra-thread"


def test_motivo_do_erro_nao_mostra_a_chave():
    resposta = httpx.Response(
        401,
        json={"error": {"message": "Incorrect API key provided: sk-proj-abc123", "code": "invalid_api_key"}},
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
    )
    with pytest.raises(httpx.HTTPStatusError) as erro:
        resposta.raise_for_status()
    motivo = llm.motivo(erro.value)
    assert motivo == "HTTP 401 invalid_api_key"
    assert "sk-" not in motivo


def test_responder_cai_no_offline_quando_o_llm_falha(monkeypatch):
    async def falha(instrucoes, pergunta):
        raise httpx.ConnectTimeout("sem internet")

    monkeypatch.setattr(llm, "OFFLINE", False)
    monkeypatch.setattr(llm, "completar", falha)
    inicio = len(barramento.historico)
    texto = asyncio.run(llm.responder("rh", "instruções", "pergunta", lambda: "resposta offline"))
    assert texto == "resposta offline"
    assert any("LLM falhou" in e.get("texto", "") for e in barramento.historico[inicio:])


def test_verificar_sem_chave(monkeypatch):
    monkeypatch.setattr(llm, "OPENROUTER_API_KEY", "")
    assert asyncio.run(llm.verificar()) == "OPENROUTER_API_KEY vazia no .env"


def test_usa_o_glm_do_openrouter_por_padrao():
    assert llm.OPENROUTER_URL == "https://openrouter.ai/api/v1/chat/completions"
    assert llm.MODELO_PADRAO == "z-ai/glm-5.3-flash"


def test_motivo_traduz_o_limite_do_modelo_gratuito():
    resposta = httpx.Response(
        429,
        json={"error": {"message": "Rate limit exceeded: free-models-per-day", "code": 429}},
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
    )
    with pytest.raises(httpx.HTTPStatusError) as erro:
        resposta.raise_for_status()
    assert llm.motivo(erro.value) == "HTTP 429 limite de uso atingido"


def test_completar_tira_o_bloco_de_raciocinio(monkeypatch):
    async def conversar(mensagens, ferramentas=None):
        return {"content": "<think>vou pensar…</think>\n Olá!"}

    monkeypatch.setattr(llm, "conversar", conversar)
    assert asyncio.run(llm.completar("instruções", "pergunta")) == "Olá!"


def _respostas_falsas(codigos: list[int]):
    chamadas = []
    codigos = iter(codigos)

    async def chamada():
        chamadas.append(1)
        return httpx.Response(next(codigos), request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"))

    return chamada, chamadas


def test_tenta_de_novo_quando_o_provedor_gratuito_esta_congestionado():
    chamada, chamadas = _respostas_falsas([429, 429, 200])
    assert asyncio.run(llm.com_novas_tentativas(chamada, esperas=(0, 0, 0))).status_code == 200
    assert len(chamadas) == 3


def test_desiste_depois_das_novas_tentativas():
    chamada, chamadas = _respostas_falsas([429, 429, 429])
    assert asyncio.run(llm.com_novas_tentativas(chamada, esperas=(0, 0))).status_code == 429
    assert len(chamadas) == 3


def test_nao_tenta_de_novo_quando_a_chave_e_invalida():
    chamada, chamadas = _respostas_falsas([401])
    assert asyncio.run(llm.com_novas_tentativas(chamada, esperas=(0, 0))).status_code == 401
    assert len(chamadas) == 1
