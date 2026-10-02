"""Ensaio da demo: roda o fluxo A2A sem depender da OpenAI.

Uso:  .venv/bin/pytest -q
"""

import asyncio
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

import smart_rh
import smart_vagas

AQUI = Path(__file__).parent


def _porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def servidor():
    """Sobe o Smart RH em modo offline numa porta livre."""
    porta = _porta_livre()
    proc = subprocess.Popen(
        [sys.executable, str(AQUI / "smart_rh.py"), "--offline", "--port", str(porta)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://localhost:{porta}"
    try:
        for _ in range(50):
            try:
                httpx.get(f"{url}/.well-known/agent-card.json", timeout=1)
                break
            except httpx.TransportError:
                time.sleep(0.2)
        else:
            pytest.fail("Smart RH não subiu — rode `python smart_rh.py --offline` para ver o erro")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=5)


# ---------- Servidor ----------

def test_card_publicado(servidor):
    card = httpx.get(f"{servidor}/.well-known/agent-card.json").json()
    assert card["name"] == "Agente Smart RH"
    assert card["skills"][0]["id"] == "perfil-time"
    assert card["capabilities"]["streaming"] is True
    assert card["supportedInterfaces"][0]["url"] == f"{servidor}/a2a"


def test_resposta_offline_ignora_caixa():
    assert "12 pessoas" in smart_rh.resposta_offline("perfil do time de PLATAFORMA?")


def test_resposta_offline_time_desconhecido():
    assert "Plataforma, Dados, Produto" in smart_rh.resposta_offline("e o time de Marketing?")


def test_fallback_quando_llm_falha(monkeypatch):
    async def sem_rede(pergunta, timeout=smart_rh.TIMEOUT_LLM):
        raise httpx.ConnectTimeout("sem internet")

    monkeypatch.setattr(smart_rh, "perguntar_llm", sem_rede)
    assert "8 pessoas" in asyncio.run(smart_rh.responder("time de Dados?", offline=False))


def test_fallback_quando_llm_responde_vazio(monkeypatch):
    async def vazio(pergunta, timeout=smart_rh.TIMEOUT_LLM):
        return ""

    monkeypatch.setattr(smart_rh, "perguntar_llm", vazio)
    assert "15 pessoas" in asyncio.run(smart_rh.responder("time de Produto?", offline=False))


def test_sem_chave_vai_para_offline(monkeypatch):
    monkeypatch.setattr(smart_rh, "OPENROUTER_API_KEY", "")
    assert smart_rh.verificar_llm() is False


def test_motivo_traduz_o_limite_do_modelo_gratuito():
    resposta = httpx.Response(
        429,
        json={"error": {"message": "Rate limit exceeded: free-models-per-day", "code": 429}},
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
    )
    with pytest.raises(httpx.HTTPStatusError) as erro:
        resposta.raise_for_status()
    assert smart_rh.motivo(erro.value) == "HTTP 429 limite de uso atingido"


def test_usa_o_glm_do_openrouter_por_padrao():
    assert smart_rh.OPENROUTER_URL == "https://openrouter.ai/api/v1/chat/completions"
    assert smart_rh.MODELO_PADRAO == "z-ai/glm-5.3-flash"


def test_resposta_do_llm_sem_bloco_de_raciocinio():
    assert smart_rh.limpar_resposta("<think>pensando…</think>\n O time tem 12 pessoas. ") == "O time tem 12 pessoas."


def test_motivo_do_erro_nao_mostra_a_chave():
    resposta = httpx.Response(
        401,
        json={"error": {"message": "Incorrect API key provided: sk-proj-abc123", "code": "invalid_api_key"}},
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )
    with pytest.raises(httpx.HTTPStatusError) as erro:
        resposta.raise_for_status()
    motivo = smart_rh.motivo(erro.value)
    assert motivo == "HTTP 401 invalid_api_key"
    assert "sk-" not in motivo


def test_porta_ocupada(capsys):
    with socket.socket() as ocupante:
        ocupante.bind(("127.0.0.1", 0))
        ocupante.listen()
        porta = ocupante.getsockname()[1]
        assert smart_rh.main(["--offline", "--port", str(porta)]) == 1
    assert "ocupada" in capsys.readouterr().out


# ---------- Cliente + fluxo completo ----------

def test_fluxo_completo(servidor, capsys):
    codigo = smart_vagas.main(["--direto", "--url", servidor, "Qual o perfil do time de Plataforma?"])
    saida = capsys.readouterr().out
    assert codigo == 0
    assert "Agente Smart RH" in saida                    # 1. descobriu pelo card
    assert "SendStreamingMessage" in saida               # 2. delegou
    assert "WORKING" in saida                            # 3. acompanhou
    assert "COMPLETED" in saida
    assert "12 pessoas" in saida                         # 4. artifact (time de Plataforma)


def test_pergunta_sem_aspas(servidor, capsys):
    codigo = smart_vagas.main(["--direto", "--url", servidor, "como", "está", "o", "time", "de", "Dados?"])
    assert codigo == 0
    assert "8 pessoas" in capsys.readouterr().out


def test_sem_pergunta_pergunta_ao_usuario_ate_enter_vazio(servidor, capsys, monkeypatch):
    respostas = iter(["time de Dados?", "e o time de Produto?", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(respostas))
    codigo = smart_vagas.main(["--direto", "--url", servidor])
    saida = capsys.readouterr().out
    assert codigo == 0
    assert saida.count("1. DESCOBRIR") == 1              # descobre uma vez só
    assert "8 pessoas" in saida
    assert "15 pessoas" in saida
    assert "12 pessoas" not in saida                     # nenhuma pergunta fixa sobre Plataforma


def test_cliente_sem_servidor(capsys):
    codigo = smart_vagas.main(["--direto", "--url", f"http://localhost:{_porta_livre()}"])
    assert codigo == 1
    assert "Suba o Smart RH primeiro" in capsys.readouterr().out


def _respostas_falsas(codigos: list[int]):
    chamadas = []
    codigos = iter(codigos)

    async def chamada():
        chamadas.append(1)
        return httpx.Response(next(codigos), request=httpx.Request("POST", smart_rh.OPENROUTER_URL))

    return chamada, chamadas


def test_tenta_de_novo_quando_o_provedor_gratuito_esta_congestionado():
    chamada, chamadas = _respostas_falsas([429, 503, 200])
    assert asyncio.run(smart_rh.com_novas_tentativas(chamada, esperas=(0, 0, 0))).status_code == 200
    assert len(chamadas) == 3


def test_nao_tenta_de_novo_quando_a_chave_e_invalida():
    chamada, chamadas = _respostas_falsas([401])
    assert asyncio.run(smart_rh.com_novas_tentativas(chamada, esperas=(0, 0))).status_code == 401
    assert len(chamadas) == 1
