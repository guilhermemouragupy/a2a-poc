"""Agente de Compliance: revisa anúncios de vaga (linguagem inclusiva, discriminação, LGPD)."""

import re

from starlette.applications import Starlette

from comum import llm, servidor

# Termo (início de palavra) → ajuste pedido. Regra simples, usada no modo offline.
TERMOS_PROIBIDOS = {
    "jovem": "não mencionar idade ('jovem')",
    "idade": "não pedir idade",
    "boa aparência": "remover 'boa aparência'",
    "sexo": "não restringir por sexo/gênero",
    "masculino": "não restringir por gênero",
    "feminino": "não restringir por gênero",
    "solteir": "não mencionar estado civil",
    "casad": "não mencionar estado civil",
    "foto": "não pedir foto (LGPD)",
    "cpf": "não pedir CPF no anúncio (LGPD)",
}

INSTRUCOES = (
    "Você é o Agente de Compliance de vagas. Revise o anúncio recebido. Verifique: linguagem inclusiva "
    "(ex.: 'Engenheiro(a)' ou 'pessoa engenheira'), ausência de requisitos discriminatórios (idade, gênero, "
    "estado civil, aparência, origem) e se o anúncio não pede dados pessoais sensíveis (LGPD). "
    "Se estiver adequado, comece a resposta com 'APROVADO' seguido de uma frase curta. "
    "Se não, comece com 'AJUSTES:' e liste no máximo 3 ajustes objetivos, numa linha só."
)


def revisao_offline(anuncio: str) -> str:
    """Revisão por regras, sem LLM."""
    texto = anuncio.lower()
    ajustes = [ajuste for termo, ajuste in TERMOS_PROIBIDOS.items() if re.search(rf"\b{re.escape(termo)}", texto)]
    if ajustes:
        return "AJUSTES: " + "; ".join(dict.fromkeys(ajustes)) + "."
    return "APROVADO — linguagem inclusiva e sem requisitos discriminatórios."


async def responder(anuncio: str) -> str:
    return await llm.responder("compliance", INSTRUCOES, anuncio, lambda: revisao_offline(anuncio))


def criar_app() -> Starlette:
    card = servidor.criar_card(
        "compliance",
        descricao="Revisa textos de vaga antes da publicação.",
        skill_id="revisar-vaga",
        skill_nome="Revisão de compliance",
        skill_descricao="Revisa um anúncio de vaga: linguagem inclusiva, requisitos discriminatórios e LGPD. Responde APROVADO ou a lista de ajustes.",
        exemplo="Revise este anúncio: ...",
    )
    return servidor.criar_app(card, servidor.AgenteSimples("parecer", "revisando o anúncio…", responder))
