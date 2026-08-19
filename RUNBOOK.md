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

**Regra permanente: a matéria "LIXO" nunca entra em nenhum passo abaixo.**
É onde o usuário joga aula de teste/descartável de propósito — nem
transcreve, nem processa, nem gera guia. Todo `select` desta seção filtra
`Subject.sigla != "LIXO"`.

**Isto acontece em duas etapas separadas, nesta ordem, e nunca a segunda
sem a primeira:**

**Etapa 0 — transcrever o que tem áudio e ainda não foi transcrito.**
Nada de IA aqui, é só rodar o Whisper (GPU local) — por isso é **um script
só, não passos manuais**: achar pendente e enfileirar é mecânico
(`POST /api/jobs/enqueue-pending-transcriptions`, já filtra fora de LIXO e
aula sem áudio/já transcrita), e `worker/main.py` chama isso sozinho antes
de drenar a fila. Não gaste turno de agente reimplementando essa consulta
— rode o script:

```powershell
& .\worker\run_local.ps1
```

(ou dê dois cliques no atalho "Transcrever aulas (Estudos)" na área de
trabalho — mesma coisa, sem terminal, sem precisar de mim.)

Isso pode levar bastante tempo numa aula longa — se for você (agente)
quem está rodando isso via PowerShell tool, rode em background e espere
terminar antes de seguir pra etapa 1. Aulas com transcrição pendente de
revisão **continuam esperando**: a etapa 1 não toca nelas até o usuário
aprovar. No fim, cada aula fica com transcrição pronta mas **`aprovado_em`
ainda nulo** — a revisão humana (`/lessons/{id}/transcricao`, conferir os
trechos de baixa confiança do Whisper e clicar "Aprovar transcrição") é
sempre manual, o runbook/script nunca aprova sozinho.

**Etapa 1 — achar aulas com transcrição aprovada, ainda sem `resumo`.**
Só entra aqui o que passou pela revisão humana da etapa 0 — é isso que
garante que a IA nunca trabalha em cima de um Whisper cheio de erro não
corrigido:

```bash
docker compose exec server python -c "
from sqlalchemy import select
from app.db import holder
from app.models import Lesson, Subject, Transcript

with holder.SessionLocal() as session:
    rows = session.execute(
        select(Lesson.id, Lesson.titulo)
        .join(Transcript, Transcript.lesson_id == Lesson.id)
        .join(Subject, Subject.id == Lesson.subject_id)
        .where(
            Lesson.resumo.is_(None),
            Transcript.aprovado_em.is_not(None),
            Subject.sigla != 'LIXO',
        )
    ).all()
    for r in rows:
        print(r.id, r.titulo)
"
```

Para cada aula encontrada aqui, faça **as duas** "outras atividades" —
aula editada (passos 2–5 abaixo) e guia de aula (seção própria, mais
adiante neste arquivo) — não só uma das duas.

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

⚠️ **Armadilha de encoding testada e confirmada — mais ampla do que parece.**
No Git Bash deste Windows, **qualquer texto acentuado passado como argumento
de shell pro `curl` corrompe silenciosamente**, sem erro nenhum: tanto
`--data-urlencode "campo=$(cat arquivo)"` (substituição de comando) quanto
`--data-urlencode "campo=Usucapião"` (literal digitado direto no comando)
viram "Usucapi�o". Confirmado nas duas formas, em dois campos diferentes,
nesta sessão (fase 6 e fase 8).

**A única forma segura é `--data-urlencode "campo@${WINPATH}"` — o curl
lendo o arquivo sozinho, nunca o bash interpolando o conteúdo numa
string.** Isso vale pra
QUALQUER campo com acento, não só `resposta` — inclusive campos curtos como
um título de assunto:

```bash
printf 'Usucapião Extraordinária' > titulo.txt   # nunca: --data-urlencode "titulo=Usucapião..."
WINPATH=$(cygpath -w titulo.txt)
curl ... --data-urlencode "titulo@${WINPATH}"
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

### Fase 8a — Assuntos

O campo `assuntos` (lista de títulos) já vem na mesma resposta da fase 6 —
não é uma passada de IA separada, é o mesmo `colar-resposta` de sempre.
Depois de colar, as propostas aparecem na tela de aprovação da aula
(`/lessons/{id}/aprovacao`), numa seção própria "Assuntos propostos".

**Aceitar** (`POST /lessons/{id}/assuntos/{proposal_id}/aceitar`, campo
`titulo`) resolve ou cria o `Assunto` global pelo slug do título — duas
aulas propondo "Posse" e "posse" caem no mesmo registro automaticamente.
Edite o título antes de aceitar se quiser que a proposta caia num assunto
que já existe com outro nome.

**Ferramentas de correção** (a IA vai fatiar demais ou de menos, é o
esperado): `/assuntos` lista tudo; `/assuntos/{id}` é a página do assunto
com **renomear** (só troca o rótulo, o slug de casamento não muda),
**fundir** (escolhe outro assunto, este desaparece e tudo migra) e
**separar** — em cada aula vinculada, um formulário move só aquele vínculo
pra outro assunto (existente ou novo, por título).

**Painel de gasto**: `/admin/gasto` — soma do mês contra o teto, e a lista
de `AiCall` recentes (manual sempre grátis).

`server/app/context/window.py` monta o contexto de um assunto concatenando
a transcrição literal de cada aula vinculada (nunca a aula editada) — hoje
é a aula inteira, não um recorte por trecho, porque o `assunto` ainda não
marca onde começa/termina dentro da aula (simplificação deliberada da fase
8a; ver o módulo pra decisão completa).

### Guia de aula (complementar à fase 6, não é uma fase própria)

Mesma regra da etapa 1 acima: só gere para aula com `Transcript.aprovado_em`
preenchido, fora da matéria LIXO. É a segunda das "duas outras atividades"
— faça junto com a aula editada, não como passo isolado.

Diferente da aula editada (schema JSON tipado): é um prompt simples que
devolve markdown corrido, reorganizando a transcrição em seções com
título — sem inventar, sem parafrasear conteúdo jurídico, preservando a
voz do professor. O prompt inteiro mora em `server/app/ai/guia.py`
(`INSTRUCTIONS_GUIA`).

**1. Baixar o pacote:**

```bash
curl -s -b "$COOKIEJAR" "http://127.0.0.1:8000/lessons/{id}/guia-pacote.md" -o guia-pacote.md
```

**2. Gerar a resposta** seguindo as instruções que já vêm no pacote.
Devolva só o markdown do guia, começando com `# título` — nada de
conversa em volta (o parser corta tudo antes do primeiro `# `, mas é mais
limpo já mandar só o markdown).

**3. Enviar de volta** (mesma regra de encoding do resto do runbook —
arquivo, nunca argumento inline):

```bash
WINPATH=$(cygpath -w /caminho/para/guia.md)
curl -s -b "$COOKIEJAR" -X POST "http://127.0.0.1:8000/lessons/{id}/colar-guia" \
  --data-urlencode "resposta@${WINPATH}"
```

**4. Validar:** `GET /lessons/{id}/guia` renderiza o markdown; confira
`repr(lesson.guia_md)` no banco pra descartar corrupção de acento, como
sempre.

Reprocessar substitui o guia inteiro — não há `deriv_key` nem reconcile
aqui (é um documento único, não uma lista de artefatos com identidade
própria).

### Fase 8b em diante

Ainda não implementadas (cloze, cards de discriminação). **Ao
implementar**: descreva aqui como achar o trabalho pendente, onde baixar o
prompt/pacote se houver, o schema esperado, e o endpoint equivalente — no
mesmo formato das seções acima.

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
