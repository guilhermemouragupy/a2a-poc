"""Agente Redator: escreve o anúncio e, antes de entregar, pede a revisão do Agente de Compliance."""

from starlette.applications import Starlette

from comum import a2a_cliente, llm, servidor
from comum.eventos import barramento

INSTRUCOES = (
    "Você é o Agente Redator de vagas. Escreva um anúncio de vaga em português, curto (até 120 palavras), com: "
    "título, uma frase sobre o time, 3 responsabilidades, 3 requisitos e a faixa salarial. "
    "Use só as informações recebidas e linguagem inclusiva. Texto simples, sem markdown. "
    "Entregue só o texto do anúncio, sem observações internas nem avisos de revisão."
)
PREFIXO_AJUSTE = "Ajuste este anúncio. Pedido de ajuste: "
SEPARADOR_ATUAL = "\n\nAnúncio atual:\n"


def rascunho_offline(pedido: str) -> str:
    """Anúncio montado sem LLM — ou, num ajuste, o anúncio atual com o ajuste anotado."""
    if pedido.startswith(PREFIXO_AJUSTE):
        ajuste, _, atual = pedido.removeprefix(PREFIXO_AJUSTE).partition(SEPARADOR_ATUAL)
        atual = atual.split("\n\n[Compliance]")[0]
        return f"{atual}\nAjuste aplicado: {ajuste}"
    campos = dict(linha.split(": ", 1) for linha in pedido.splitlines() if ": " in linha)
    linhas = [f"Vaga: {campos.get('Pedido', pedido).strip()}"]
    if "Perfil do time" in campos:
        linhas.append(f"Sobre o time: {campos['Perfil do time']}")
    linhas += [
        "Responsabilidades: evoluir as entregas do time; colaborar com produto e dados; participar das revisões técnicas.",
        "Requisitos: experiência compatível com o nível da vaga; boa comunicação; vontade de aprender.",
    ]
    if "Faixa salarial" in campos:
        linhas.append(f"Remuneração: {campos['Faixa salarial']}")
    linhas.append("Todas as pessoas são bem-vindas: valorizamos a diversidade.")
    return "\n".join(linhas)


async def responder(pedido: str) -> str:
    anuncio = await llm.responder("redator", INSTRUCOES, pedido, lambda: rascunho_offline(pedido))

    # Agente chamando agente: o Redator descobre o Compliance e pede a revisão.
    card = await a2a_cliente.descobrir("redator", "compliance")
    parecer = await a2a_cliente.enviar("redator", "compliance", f"Revise este anúncio de vaga:\n\n{anuncio}", card=card)
    if parecer.estado != a2a_cliente.CONCLUIDA:
        return f"{anuncio}\n\n[Compliance] revisão indisponível — revisar manualmente."
    if parecer.texto.strip().upper().startswith("APROVADO"):
        return f"{anuncio}\n\n[Compliance] {parecer.texto.strip()}"

    barramento.publicar("pensando", agente="redator", texto="aplicando os ajustes do Compliance…")
    revisado = await llm.responder(
        "redator",
        INSTRUCOES,
        f"{pedido}\n\nReescreva o anúncio abaixo aplicando estes ajustes do Compliance: {parecer.texto}\n\nAnúncio:\n{anuncio}",
        lambda: anuncio,
    )
    return f"{revisado}\n\n[Compliance] {parecer.texto.strip()} → anúncio revisado pelo Redator."


def criar_app() -> Starlette:
    card = servidor.criar_card(
        "redator",
        descricao="Escreve anúncios de vaga.",
        skill_id="escrever-vaga",
        skill_nome="Redação de vaga",
        skill_descricao="Escreve o anúncio de uma vaga a partir do cargo, do perfil do time e da faixa salarial, e passa o texto pela revisão do Compliance antes de entregar.",
        exemplo="Escreva o anúncio de uma vaga de Engenheiro(a) de Software Pleno.",
    )
    return servidor.criar_app(card, servidor.AgenteSimples("anuncio", "escrevendo o anúncio…", responder))
