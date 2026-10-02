import json
import re
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest


def test_pagina_e_agentes(sistema):
    pagina = httpx.get(f"{sistema}/")
    assert pagina.status_code == 200
    assert 'id="mapa"' in pagina.text
    dados = httpx.get(f"{sistema}/agentes").json()
    assert [a["id"] for a in dados["agentes"]] == ["voce", "recrutador", "rh", "remuneracao", "redator", "compliance"]
    assert all(a["card"] for a in dados["agentes"][1:])
    assert dados["modelo"] == "offline"


def _ler_ate(linhas, tipo_final: str, vistos: list[str]) -> dict:
    for linha in linhas:
        if linha.startswith("data:"):
            evento = json.loads(linha.removeprefix("data:"))
            vistos.append(evento["tipo"])
            if evento["tipo"] == tipo_final:
                return evento
    raise AssertionError(f"o stream terminou sem '{tipo_final}'")


def test_painel_transmite_o_fluxo_e_recebe_a_aprovacao(sistema):
    vistos: list[str] = []
    with httpx.Client(timeout=httpx.Timeout(15)) as cliente:
        with cliente.stream("GET", f"{sistema}/eventos") as stream:
            linhas = stream.iter_lines()
            pedido = {"texto": "Vaga de Engenheiro(a) de Software Pleno no time de Plataforma"}
            assert cliente.post(f"{sistema}/pedido", json=pedido).status_code == 200
            aprovacao = _ler_ate(linhas, "aprovacao", vistos)
            assert "12 pessoas" in aprovacao["texto"]
            assert cliente.post(f"{sistema}/resposta", json={"texto": "aprovar"}).status_code == 200
            fim = _ler_ate(linhas, "fim", vistos)
    assert fim["estado"] == "TASK_STATE_COMPLETED"
    assert {"inicio", "descoberta", "mensagem", "estado", "artifact"} <= set(vistos)
    historico = httpx.get(f"{sistema}/historico").json()["eventos"]
    assert historico[0]["tipo"] == "inicio"
    assert historico[-1]["tipo"] == "fim"


def test_pedido_vazio_e_resposta_sem_aprovacao_pendente(sistema):
    assert httpx.post(f"{sistema}/pedido", json={"texto": "  "}).status_code == 400
    assert httpx.post(f"{sistema}/resposta", json={"texto": "aprovar"}).status_code == 409


def test_js_da_pagina_e_valido(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    html = (Path(__file__).parent.parent / "painel" / "index.html").read_text()
    script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    arquivo = tmp_path / "pagina.js"
    arquivo.write_text(script)
    resultado = subprocess.run([node, "--check", str(arquivo)], capture_output=True, text=True)
    assert resultado.returncode == 0, resultado.stderr
