# POC 2 A2A — Abertura de vaga com 5 agentes

Você faz um pedido numa página web e vê, ao vivo, 5 agentes conversando pelo protocolo A2A:
o **Recrutador** lê os crachás dos outros agentes, o LLM decide quem chamar, o **Redator** chama
o **Compliance** por conta própria, e no fim a Task pausa esperando a sua aprovação.

Para entender o fluxo passo a passo, veja [COMO-FUNCIONA.md](COMO-FUNCIONA.md).

## Preparar (uma vez)

    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt

Crie um arquivo `.env` nesta pasta com sua chave do OpenRouter (`OPENROUTER_API_KEY=sk-or-...`; crie em https://openrouter.ai/keys). Sem chave, tudo roda em modo offline.

## Ensaio (antes de entrar na sala, ~2s, sem internet nem chave)

    .venv/bin/pytest -q

## Na apresentação

    .venv/bin/python rodar.py            # sem internet: acrescente --offline

Abra http://localhost:8000 e clique numa sugestão (ou digite um pedido).

- **Mapa (esquerda):** a linha entre dois agentes acende quando uma mensagem passa; o selo mostra o estado da Task de cada agente. Clique num agente para ver o crachá (Agent Card).
- **Conversa (direita):** cada mensagem A2A, estado e artifact. Clique numa mensagem para ver o JSON cru.
- **Aprovação:** no fim, o Recrutador pausa (`INPUT_REQUIRED`). Aprove ou peça um ajuste (ex.: "deixe claro que é remoto").
- **Ritmo de apresentação:** ligado, os eventos aparecem com um intervalo mínimo para a plateia acompanhar.
- **Revisão:** http://localhost:8000/?replay=1 mostra a última conversa inteira, sem animação.

## Se algo der errado

| Sintoma | O que fazer |
|---|---|
| `⚠ z-ai/glm-5.3-flash indisponível (OPENROUTER_API_KEY vazia no .env) → modo offline` | Coloque a chave no `.env` e reinicie |
| `⚠ z-ai/glm-5.3-flash indisponível (HTTP 401 chave inválida)` | Chave errada no `.env` (`HTTP 402 sem créditos`: recarregue no OpenRouter) |
| `HTTP 429 limite de uso atingido` (no início ou no meio da demo) | Provedor congestionado: a POC tenta de novo 3 vezes; se persistir, aquele agente responde offline e a demo segue |
| `HTTP 400` depois de trocar `OPENROUTER_MODEL` | O modelo novo não aceita algum parâmetro (ex.: o nível de raciocínio): volte ao padrão ou ajuste `comum/llm.py` |
| `Portas ocupadas: [...]` | Já tem uma POC 2 aberta: feche-a (Ctrl+C) |
| Selo "modo offline" na página | A demo segue igual, com respostas montadas dos dados fictícios |
| "já tem uma conversa em andamento" | Espere a conversa atual terminar (ou aprove/peça ajuste) |

Configuração no `.env`: `OPENROUTER_API_KEY` e `OPENROUTER_MODEL` (padrão `z-ai/glm-5.3-flash`). Cada conversa faz ~6 chamadas ao LLM e custa uma fração de centavo; com o LLM, a vaga chega à aprovação em ~20s.
