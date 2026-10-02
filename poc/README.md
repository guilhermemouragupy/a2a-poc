# POC A2A — Smart Vagas ↔ Smart RH

Demo local do protocolo A2A: o **Agente Smart Vagas** descobre o **Agente Smart RH**
pelo Agent Card, delega uma pergunta, acompanha a Task por streaming e recebe um Artifact.

- `smart_rh.py` — servidor A2A com o SDK oficial (`a2a-sdk`), responde usando o GLM 5.3 Flash via OpenRouter (`z-ai/glm-5.3-flash`)
- `smart_vagas.py` — cliente **sem SDK**: só HTTP + JSON, mostrando o que trafega

Para entender o fluxo passo a passo, veja [COMO-FUNCIONA.md](COMO-FUNCIONA.md).

## Preparar (uma vez)

    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt

Crie um arquivo `.env` nesta pasta com sua chave do OpenRouter (`OPENROUTER_API_KEY=sk-or-...`; crie em https://openrouter.ai/keys). Sem chave, a demo roda em modo offline.

## Ensaio (antes de entrar na sala, ~2s, sem internet nem chave)

    .venv/bin/pytest -q

## Na apresentação

Terminal 1 — Agente Smart RH:

    .venv/bin/python smart_rh.py            # sem internet: acrescente --offline

Terminal 2 — Agente Smart Vagas:

    .venv/bin/python smart_vagas.py

Ele descobre o Smart RH (passo 1) e pede a pergunta. Digite o que quiser; Enter avança cada passo.
Depois da resposta, ele pede outra pergunta — Enter vazio sai. Para rodar uma pergunta só
(com aspas: no zsh, o `?` solto vira curinga):
`.venv/bin/python smart_vagas.py "qual o perfil do time de Dados?"`

Perguntas para testar:

| Tipo | Pergunta | O que o Smart RH faz |
|---|---|---|
| Direta | Qual o perfil do time de Plataforma? | Lê os dados |
| Raciocínio | Qual time tem a maior rotatividade proporcional ao tamanho? | Calcula: Dados, 2 de 8 = 25% |
| Raciocínio | Se eu contratar 2 juniores para Plataforma, como fica a senioridade? | Recalcula: 14 pessoas, ~50% sênior |
| Sem resposta | Qual o salário médio do time de Dados? | Diz que não tem esse dado |
| Fora do tema | Qual a capital da França? | Recusa: só tem dados de times |

## Se algo der errado

| Sintoma | O que fazer |
|---|---|
| `⚠ OPENROUTER_API_KEY vazia no .env → modo offline` | Coloque a chave no `.env` e reinicie o Smart RH |
| `⚠ z-ai/glm-5.3-flash indisponível (HTTP 401 chave inválida) → modo offline` | Chave errada no `.env`. Outros motivos: `HTTP 402 sem créditos` (recarregue no OpenRouter), `HTTP 429 limite de uso atingido` (provedor congestionado: a POC já tenta de novo 3 vezes), `HTTP 400`/`HTTP 404` (modelo trocado em `OPENROUTER_MODEL` não aceita os parâmetros ou não existe), `ConnectError` (sem internet) |
| Qualquer `→ modo offline` / `→ resposta offline` | A demo segue igual, com resposta montada dos dados fictícios |
| `Porta 9999 ocupada` | Já tem um Smart RH aberto: feche-o (Ctrl+C) ou use `--port 9998` nos dois lados (`--url http://localhost:9998` no cliente) |
| `Suba o Smart RH primeiro` | Rode o terminal 1 antes do 2 |

Configuração no `.env`: `OPENROUTER_API_KEY` (obrigatória para usar o LLM) e `OPENROUTER_MODEL` (padrão `z-ai/glm-5.3-flash`, ~US$ 0,15 por milhão de tokens de entrada: uma pergunta custa uma fração de centavo).
