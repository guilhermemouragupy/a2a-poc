"""Catálogo interno: quem são os agentes e onde cada um mora.

Na vida real seria um registro de agentes da empresa; aqui é uma tabela.
"""

AGENTES = {
    "recrutador": {"nome": "Agente Recrutador", "emoji": "🤖", "porta": 10001},
    "rh": {"nome": "Agente Smart RH", "emoji": "👥", "porta": 10002},
    "remuneracao": {"nome": "Agente de Remuneração", "emoji": "💰", "porta": 10003},
    "redator": {"nome": "Agente Redator", "emoji": "✍️", "porta": 10004},
    "compliance": {"nome": "Agente de Compliance", "emoji": "⚖️", "porta": 10005},
}
PORTA_PAINEL = 8000


def url(agente_id: str) -> str:
    return f"http://localhost:{AGENTES[agente_id]['porta']}"
