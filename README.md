# a2a-poc

Provas de conceito do protocolo **A2A (Agent2Agent)** num cenário de RH com dados fictícios.
Cada pasta é independente: tem seu próprio `.venv`, `requirements.txt`, `.env` e testes.

| POC | O que mostra | Como roda |
|---|---|---|
| [poc/](poc/README.md) | **2 agentes.** O Smart Vagas descobre o Smart RH pelo Agent Card, delega uma pergunta, acompanha a Task por streaming e recebe um Artifact. O cliente não usa SDK (só HTTP + JSON), para mostrar o que trafega. | 2 terminais; Smart RH na porta `9999` |
| [poc2/](poc2/README.md) | **5 agentes + painel web.** O Recrutador lê os Agent Cards e o LLM decide quem chamar; o Redator chama o Compliance por conta própria; no fim a Task pausa em `INPUT_REQUIRED` esperando sua aprovação. | 1 comando; painel em http://localhost:8000, agentes nas portas `10001`–`10005` |

Para apresentar, comece pela `poc/` (o protocolo cru) e depois passe para a `poc2/` (orquestração entre vários agentes).

## Pré-requisitos

- Python 3.13
- Chave do OpenRouter (opcional): crie em https://openrouter.ai/keys. Sem chave, as duas POCs rodam em **modo offline**, com respostas montadas dos dados fictícios.

## Começo rápido

Dentro da pasta da POC (`poc` ou `poc2`):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Crie um `.env` na mesma pasta (ele é ignorado pelo git):

```bash
OPENROUTER_API_KEY=sk-or-...
# OPENROUTER_MODEL=z-ai/glm-5.3-flash   # opcional; este é o padrão
```

Ensaio (alguns segundos, sem internet nem chave):

```bash
.venv/bin/pytest -q
```

Para rodar:

```bash
# poc/  — dois terminais
.venv/bin/python smart_rh.py      # terminal 1 (sem internet: --offline)
.venv/bin/python smart_vagas.py   # terminal 2

# poc2/ — um comando, depois abra http://localhost:8000
.venv/bin/python rodar.py         # sem internet: --offline
```

Perguntas de exemplo, o que aparece na tela e a tabela de erros estão no README de cada POC.

## Estrutura

```
poc/
  smart_rh.py       servidor A2A (a2a-sdk) que responde com o LLM
  smart_vagas.py    cliente A2A só com HTTP + JSON
  test_demo.py      ensaio da demo
poc2/
  rodar.py          sobe os 5 agentes e o painel
  agentes/          Recrutador, Smart RH, Remuneração, Redator, Compliance
  comum/            catálogo de agentes, cliente A2A, servidor, LLM, eventos
  painel/           página web que mostra a conversa ao vivo
  tests/            ensaio da demo
```
