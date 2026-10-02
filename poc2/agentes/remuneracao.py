"""Agente de Remuneração: faixas salariais (tabela fictícia)."""

import json

from starlette.applications import Starlette

from comum import llm, servidor

# Salário mensal CLT — fictício, só para a demo.
FAIXAS = {
    "Engenharia de Software": {"júnior": "R$ 6–9 mil", "pleno": "R$ 11–15 mil", "sênior": "R$ 17–23 mil"},
    "Dados": {"júnior": "R$ 6–8 mil", "pleno": "R$ 10–14 mil", "sênior": "R$ 16–21 mil"},
    "Produto": {"júnior": "R$ 5–8 mil", "pleno": "R$ 10–13 mil", "sênior": "R$ 15–20 mil"},
}
PALAVRAS_AREA = {
    "Engenharia de Software": ["engenh", "software", "desenvolv"],
    "Dados": ["dados", "data"],
    "Produto": ["produto", "product"],
}
PALAVRAS_NIVEL = {"júnior": ["júnior", "junior"], "pleno": ["pleno"], "sênior": ["sênior", "senior"]}

INSTRUCOES = (
    "Você é o Agente de Remuneração. Responda em português, em no máximo 2 frases, com a faixa salarial mensal (CLT) "
    "do cargo e nível pedidos, usando apenas a tabela abaixo. Se o cargo ou o nível não estiverem na tabela, diga isso.\n\n"
    f"Tabela: {json.dumps(FAIXAS, ensure_ascii=False)}"
)


def _achar(texto: str, palavras: dict[str, list[str]]) -> str | None:
    return next((chave for chave, lista in palavras.items() if any(p in texto for p in lista)), None)


def resposta_offline(pergunta: str) -> str:
    """Resposta montada só com a tabela, sem LLM."""
    texto = pergunta.lower()
    area, nivel = _achar(texto, PALAVRAS_AREA), _achar(texto, PALAVRAS_NIVEL)
    if area and nivel:
        return f"Faixa salarial para {area} ({nivel}): {FAIXAS[area][nivel]} por mês (CLT)."
    if area:
        faixas = "; ".join(f"{n}: {f}" for n, f in FAIXAS[area].items())
        return f"Faixas para {area} — {faixas} por mês (CLT)."
    return "Tenho faixas para Engenharia de Software, Dados e Produto (júnior, pleno e sênior). Para qual cargo e nível?"


async def responder(pergunta: str) -> str:
    return await llm.responder("remuneracao", INSTRUCOES, pergunta, lambda: resposta_offline(pergunta))


def criar_app() -> Starlette:
    card = servidor.criar_card(
        "remuneracao",
        descricao="Informa faixas salariais de mercado usadas pela empresa.",
        skill_id="faixa-salarial",
        skill_nome="Faixa salarial",
        skill_descricao="Informa a faixa salarial mensal (CLT) de um cargo por área (Engenharia de Software, Dados, Produto) e nível (júnior, pleno, sênior).",
        exemplo="Qual a faixa para Engenharia de Software pleno?",
    )
    return servidor.criar_app(card, servidor.AgenteSimples("faixa-salarial", "consultando a tabela de faixas…", responder))
