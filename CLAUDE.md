# Estudos — sistema de estudo do curso de Direito

**O plano completo está em [PLANO.md](PLANO.md).** Leia antes de qualquer implementação — ele traz a arquitetura, o modelo de dados, as fases e as decisões já fechadas.

## Como executar

O trabalho é dividido em **quatro entregas**, cada uma utilizável sozinha:

| | Entrega | Fases | Fim da entrega |
|---|---|---|---|
| **A** | Capturar | 0–5 | Nenhuma aula se perde; tudo transcrito, ouvível e buscável |
| **B** | Estudar | 6–8 | O ciclo fecha: aula vira material de estudo e cards revisados |
| **C** | Corpus | 9–12 | Livros, slides e anotações entram; glossário marca tudo |
| **D** | Treinar | 13–15 | Produção falada e escrita, mapa, destaques e plano da prova |

Peça uma fase por vez: *"execute a fase 3 do PLANO.md"*. Confira o bloco de verificação correspondente antes de passar para a seguinte.

A **Entrega A não depende de nada externo além do DNS**. A chave da API só é necessária na fase 6; a service account do Google, na 9; as datas de prova, na 14.

**Toda passada de IA (fase 6 em diante) é feita manualmente por um chat do Claude Code, não pela API paga da Anthropic** — decisão do usuário para não gastar com API. Antes de processar qualquer aula/material com IA, leia [RUNBOOK.md](RUNBOOK.md): ele traz o passo a passo (achar pendências, baixar o prompt, gerar a resposta, colar de volta) e deve ganhar uma seção nova toda vez que uma fase futura envolver IA.

## Ambiente de teste — sempre Docker, nunca uvicorn solto no host

**Testar e "rodar o servidor" significa `docker compose`, não `uvicorn app.main:app` direto na venv do host.** O container roda a mesma imagem (Debian slim) que vai pra VPS (Ubuntu 24.04 + Docker) — é o mais próximo de produção que dá pra chegar localmente. Rodar uvicorn direto no Windows já aconteceu por engano numa sessão e foi corrigido pelo usuário; não repita.

```bash
docker compose build server              # SEMPRE depois de qualquer mudança de código —
                                          # o Dockerfile faz COPY, não bind-mount, então o
                                          # container antigo continua servindo código velho
                                          # até reconstruir
docker compose up -d                     # recria o container com a imagem nova
docker compose exec server python -m alembic upgrade head   # migração não roda sozinha no start
```

`docker-compose.override.yml` já expõe a porta 8000 direto (sem Caddy, sem certificado) — acesse em `http://127.0.0.1:8000/?k=<ACCESS_TOKEN>` (token no `.env` da raiz). O worker de transcrição (GPU local, `& .\worker\run_local.ps1`) já aponta pra esse mesmo servidor via `SERVER_URL` no `.env` — não precisa trocar nada pra testar o ciclo upload → transcrição → processamento contra o container.

## Antes de mexer em qualquer coisa

1. **Leia "Decisões fechadas — não reabrir"** no PLANO.md. Cada linha traz o motivo de uma alternativa já descartada — evita repropor o que foi discutido e rejeitado.
2. **Leia "Integridade" e "Limites operacionais"**. São regras que precisam existir **antes da fase 6**: chave de derivação nos artefatos gerados, ciclo de vida dos chunks, matéria fora do chunk, idempotência, modo manutenção na restauração e clientes de IA injetáveis. Depois da fase 6, cada uma custa migração e reprocessamento.

## Contexto fixo

- **Domínio:** `drwyver.mecadosjogos.app.br` (temporário)
- **Infra:** VPS Ubuntu 24.04 com Docker · workers com GPU no desktop (RTX 4070) e no notebook (RTX 3060)
- **Stack:** Python 3.12 · FastAPI · SQLite (WAL + FTS5) · SQLAlchemy 2.0 + Alembic · Jinja2 + HTMX · faster-whisper · ffmpeg · Caddy
- **Matérias do semestre:** Teoria Geral do Direito Civil · Ciência Política · História do Direito · Teoria Geral do Crime · Direitos Humanos

## Princípio que atravessa o sistema

A mídia crua é a verdade final e fica sempre a um toque (*▸ ouvir o original*, *▸ ver a página original*). A transcrição literal é a fonte de trabalho. O recorte — por intervalo de tempo ou de páginas — é o que vai para a IA. **A aula editada é material de leitura e índice, nunca fonte**: paráfrase em texto jurídico distorce silenciosamente.
