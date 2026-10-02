"""Agente Smart RH: perfil dos times (dados fictícios)."""

import json

from starlette.applications import Starlette

from comum import llm, servidor

# Dados fictícios — só para a demo.
TIMES = {
    "Plataforma": {"headcount": 12, "senioridade": {"sênior": 7, "pleno": 4, "júnior": 1}, "desligamentos_6_meses": 1},
    "Dados": {"headcount": 8, "senioridade": {"sênior": 3, "pleno": 3, "júnior": 2}, "desligamentos_6_meses": 2},
    "Produto": {"headcount": 15, "senioridade": {"sênior": 5, "pleno": 7, "júnior": 3}, "desligamentos_6_meses": 0},
}

INSTRUCOES = (
    "Você é o Agente Smart RH. Responda em português, em no máximo 3 frases, usando apenas os dados abaixo. "
    "Pode fazer contas e comparações entre os times. "
    "Se a pergunta não puder ser respondida com esses dados, diga isso claramente.\n\n"
    f"Dados dos times: {json.dumps(TIMES, ensure_ascii=False)}"
)


def resposta_offline(pergunta: str) -> str:
    """Resposta montada só com os dados, sem LLM."""
    for nome, dados in TIMES.items():
        if nome.lower() in pergunta.lower():
            s = dados["senioridade"]
            return (
                f"O time de {nome} tem {dados['headcount']} pessoas "
                f"({s['sênior']} sênior, {s['pleno']} pleno, {s['júnior']} júnior) "
                f"e teve {dados['desligamentos_6_meses']} desligamento(s) nos últimos 6 meses."
            )
    return f"Tenho dados dos times {', '.join(TIMES)}. Sobre qual deles você quer saber?"


async def responder(pergunta: str) -> str:
    return await llm.responder("rh", INSTRUCOES, pergunta, lambda: resposta_offline(pergunta))


def criar_app() -> Starlette:
    card = servidor.criar_card(
        "rh",
        descricao="Responde sobre os times: headcount, senioridade e histórico de desligamentos.",
        skill_id="perfil-time",
        skill_nome="Perfil do time",
        skill_descricao="Retorna headcount, distribuição de senioridade e desligamentos recentes de um time (Plataforma, Dados ou Produto).",
        exemplo="Qual o perfil do time de Plataforma?",
    )
    return servidor.criar_app(card, servidor.AgenteSimples("perfil-time", "consultando dados do time…", responder))
