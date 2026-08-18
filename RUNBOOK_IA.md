# Runbook de IA manual

Este arquivo é para um chat novo (sem o histórico da implementação) saber
exatamente como fazer, sozinho, o trabalho que a API paga da Anthropic
faria — sem gastar um centavo. O usuário decidiu não usar
`ANTHROPIC_API_KEY` por padrão; o caminho abaixo é o caminho principal, não
um fallback.

**Regra permanente para quem edita este projeto:** toda vez que uma fase
nova envolver alguma passada de IA (fase 8 em diante — assuntos, glossário,
mapa, produção falada/escrita, etc.), adicione uma seção nova em
"Fluxos por fase" abaixo, no mesmo formato das existentes, antes de
considerar a fase concluída. Sem isso este runbook fica defasado e o
próximo chat não sabe o que fazer.

## Por que isso funciona sem custo

O sistema tem dois caminhos para cada passada de IA, gerados a partir do
**mesmo prompt** (`server/app/ai/bridge.py`): automático (chama a API,
`via="automatico"`, conta no teto mensal) e manual (você cola a resposta,
`via="manual"`, `custo_usd=0`, nunca conta no teto). Um chat do Claude Code
processando manualmente ocupa o seu plano de assinatura, não a API metered
— é isso que zera o custo.

## Ambiente

Hoje (2026) só existe o Docker local — não há VPS em produção ainda. Tudo
abaixo usa `http://127.0.0.1:8000`. Quando a VPS existir de verdade, troque
a URL base pela URL/túnel da VPS; o resto do runbook não muda (o caminho
manual é o mesmo local ou remoto).

```bash
docker compose ps                      # confirma que o server está de pé
docker compose up -d server            # se não estiver
```

Autenticação: pegue `ACCESS_TOKEN` do `.env` da raiz do repo. Todo comando
`curl` abaixo assume um cookie jar já autenticado:

```bash
TOKEN=$(grep '^ACCESS_TOKEN=' .env | cut -d= -f2)
COOKIEJAR=$(mktemp)
curl -s -c "$COOKIEJAR" "http://127.0.0.1:8000/?k=$TOKEN" -o /dev/null
# use -b "$COOKIEJAR" em todo curl daqui pra frente
```

## Fluxos por fase

### Fase 6 — Processar aula (resumo, aula editada, índice, artigos, datas, cards)

**1. Achar aulas pendentes** (têm transcrição, ainda sem `resumo`):

```bash
docker compose exec server python -c "
from sqlalchemy import select
from app.db import holder
from app.models import Lesson, Transcript

with holder.SessionLocal() as session:
    rows = session.execute(
        select(Lesson.id, Lesson.titulo, Lesson.subject_id)
        .join(Transcript, Transcript.lesson_id == Lesson.id)
        .where(Lesson.resumo.is_(None))
    ).all()
    for r in rows:
        print(r.id, r.titulo)
"
```

**2. Baixar o pacote** (prompt + transcrição + schema, tudo num arquivo):

```bash
curl -s -b "$COOKIEJAR" "http://127.0.0.1:8000/lessons/{id}/pacote.md" -o pacote.md
```

**3. Ler `pacote.md` e gerar a resposta.** As instruções e o JSON Schema já
estão dentro do arquivo — siga-as ao pé da letra. Os pontos que mais
importam (do PLANO.md, "Integridade"):

- **Não invente.** Todo bloco carrega `start_s`/`end_s` do trecho de
  origem real na transcrição — é o que liga `▸ ouvir o original`. Número
  de artigo, data, citação: só se estiver literalmente na transcrição.
- **A aula editada é material de leitura, nunca fonte.** Reescreva pra
  clareza, mas sem parafrasear conceito jurídico a ponto de distorcer.
- Use os sinais calculados em código (repetição, ritmo) que já vêm no
  pacote — eles já apontam candidatos a `destaque-prova`/`ditado`; não
  refaça esse trabalho.
- Devolva **um único bloco ` ```json `** com o JSON completo — é o que
  `server/app/ai/parse.py` procura (pega o último bloco json do texto; se
  não achar nenhum, tenta o texto inteiro).

**4. Enviar de volta:**

```bash
curl -s -b "$COOKIEJAR" -X POST "http://127.0.0.1:8000/lessons/{id}/colar-resposta" \
  --data-urlencode "resposta@${WINPATH}"
```

(salve sua resposta em `resposta.md` antes — precisa ter o bloco ` ```json `)

⚠️ **Armadilha de encoding testada e confirmada:** no Git Bash deste
Windows, `--data-urlencode "resposta=$(cat resposta.md)"` (substituição de
shell) **corrompe acentos** — "usucapião" vira "usucapi�o" silenciosamente,
sem erro nenhum. Deixe o `curl` ler o arquivo direto, com caminho Windows
(`cygpath -w`), não via `$(cat ...)`:

```bash
WINPATH=$(cygpath -w /caminho/para/resposta.md)
```

Depois de colar, **sempre confira no banco** que o texto não corrompeu
(não confie só no status 303):

```bash
docker compose exec server python -c "
from app.db import holder
from app.models import Lesson
with holder.SessionLocal() as session:
    print(repr(session.get(Lesson, {id}).resumo))
"
```

**5. Validar:**

```bash
curl -s -b "$COOKIEJAR" "http://127.0.0.1:8000/lessons/{id}/aula-editada" | grep -o "Resumo\|error" 
curl -s -b "$COOKIEJAR" "http://127.0.0.1:8000/lessons/{id}/aprovacao" -o /dev/null -w "%{http_code}\n"
```

Reprocessar a mesma aula depois é seguro — o `reconcile()` por `deriv_key`
preserva o que você já editou/aceitou e só atualiza o que mudou
(`server/app/ai/reconcile.py`).

### Fase 7 — Revisão espaçada

Não usa IA (SM-2 é determinístico, sem chamada nenhuma). Nada a fazer aqui.

### Fase 8 em diante

Ainda não implementadas. **Ao implementar**: descreva aqui como achar o
trabalho pendente, onde baixar o prompt/pacote, o schema esperado, e o
endpoint de "colar resposta" equivalente — no mesmo formato da fase 6
acima.

## Custo

Toda passada manual grava uma linha em `AiCall` com `via="manual"` e
`custo_usd=0.0`, junto das automáticas (se algum dia forem usadas) — dá pra
conferir o histórico:

```bash
docker compose exec server python -c "
from sqlalchemy import select
from app.db import holder
from app.models import AiCall

with holder.SessionLocal() as session:
    for c in session.scalars(select(AiCall).order_by(AiCall.criado_em.desc())).all():
        print(c.criado_em, c.lesson_id, c.via, c.modelo, c.custo_usd)
"
```
