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
quem está rodando isso via PowerShell tool, **rode em primeiro plano
(nunca `run_in_background: true`) e deixe o próprio comando retornar**,
não um aviso de conclusão numa notificação depois. Isso importa
especialmente em execução não-interativa (`claude -p`, sem sessão
aberta, usada pelo atalho "Processar aulas pendentes"): não existe um
"turno seguinte" pra uma notificação de background chegar ali, então
rodar em background abandona o job **reivindicado e travado**, sem
ninguém de fato transcrevendo — bug real, já aconteceu (o job ficou
"claimed" até o timeout de 15 min de reivindicação obsoleta liberar de
novo, `server/app/routes/jobs.py::_reclaim_stale`). Aulas com transcrição
pendente de revisão **continuam esperando**: a etapa 1 não toca nelas até
o usuário aprovar. No fim, cada aula fica com transcrição pronta mas
**`aprovado_em` ainda nulo** — a revisão humana (`/lessons/{id}/transcricao`,
conferir os trechos de baixa confiança do Whisper e clicar "Aprovar
transcrição") é sempre manual, o runbook/script nunca aprova sozinho.

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

Para cada aula encontrada aqui, siga os passos 2–5 abaixo. **Uma única
leitura da transcrição gera tudo de uma vez** — aula editada, cards,
propostas e o guia de aula (`Lesson.guia_md`) saem da mesma resposta;
não tem passo separado pra guia (isso mudou — até esta versão do
runbook, guia de aula era uma segunda chamada, lendo a transcrição de
novo do zero, puro desperdício).

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
curl -s -b "$COOKIEJAR" "http://127.0.0.1:8000/lessons/{id}/guia" -o /dev/null -w "%{http_code}\n"
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

`server/app/context/window.py` monta o contexto de um assunto concatenando
a transcrição literal de cada aula vinculada (nunca a aula editada) — hoje
é a aula inteira, não um recorte por trecho, porque o `assunto` ainda não
marca onde começa/termina dentro da aula (simplificação deliberada da fase
8a; ver o módulo pra decisão completa).

**Guia de aula** (`Lesson.guia_md`) vem no mesmo `resposta.md` acima, campo
`guia_md` do JSON — não é mais um passo separado. Reprocessar substitui o
guia inteiro — não há `deriv_key` nem reconcile aqui (é um documento
único, não uma lista de artefatos com identidade própria), mas segue
saindo da mesma leitura da aula editada, cards e propostas.

### Fase 8b — Cloze e cards de discriminação

**Não é uma passada de IA nova.** As duas features nascem do que a
etapa 1 da fase 6 já processa — não tem pacote pra baixar nem resposta pra
colar aqui.

**Cloze** é puro código: `server/app/study/cloze.py` escolhe as palavras a
mascarar dentro dos blocos `ditado`/`conceito` da aula editada, direto na
tela `/lessons/{id}/aula-editada` — botão "Modo estudo (cloze)" no topo,
clique numa palavra mascarada revela. Nada a rodar manualmente.

**Cards de discriminação** vêm do campo `pares_confundiveis`, que já fazia
parte do schema da fase 6 mas ficava só guardado cru em
`AiCall.raw_response_json`, sem virar nada visível — a fase 8b passa a
persistir cada par como um `CardProposal` com `tipo="discriminacao"`
(mesma tabela dos cards de sempre, mesma fila SM-2, mesma tela de
aprovação, numa seção própria "Pares de discriminação propostos").

**Isso muda a etapa 3 (gerar a resposta) da fase 6**: além de
termo_a/termo_b/eixo_distincao, preencha também `start_s_a`/`end_s_a` e
`start_s_b`/`end_s_b` — o instante em que cada termo foi explicado na
transcrição — sempre que der pra identificar um trecho claro. Se não der,
deixe os quatro como `null`; o par ainda funciona, só sem os botões de
▸ ouvir de cada lado. `server/app/ai/schemas.py` (`ConfusablePairOut`) e a
seção "PARES CONFUNDÍVEIS" de `server/app/ai/bridge.py` (`INSTRUCTIONS`)
têm o texto completo — já vêm dentro do `pacote.md` que você baixa na
etapa 2, nada de novo pra decorar.

**Aulas já processadas antes desta versão do schema** (resposta colada sem
esses quatro campos) simplesmente não tinham `pares_confundiveis` virando
card nenhum — o campo era validado e descartado. Pra elas ganharem cards
de discriminação, **reprocesse a aula** (etapa 1 de novo, mesma aula):
reprocessar é seguro, preserva o que você já editou/aceitou
(`reconcile()` por `deriv_key`, igual ao resto da fase 6).

**Validar:**

```bash
curl -s -b "$COOKIEJAR" "http://127.0.0.1:8000/lessons/{id}/aprovacao" | grep -o "Pares de discriminação propostos ([0-9]*)"
curl -s -b "$COOKIEJAR" "http://127.0.0.1:8000/lessons/{id}/aula-editada" | grep -o "cloze-word" | head -1
```

### Fase 10 — Transcrever páginas de livro

**Não usa a API de visão da Anthropic.** Decisão do usuário: em vez de
`claude-haiku-4-5` via API paga (o que o PLANO.md descrevia originalmente),
o próprio Claude Code lê a foto direto — o Read tool já lê imagem
nativamente. Zero chamada paga, mesmo princípio do resto do runbook.

**Sem portão de aprovação antes de transcrever.** Diferente de áudio
(Whisper transcreve sozinho, sem curadoria — por isso existe
`Transcript.aprovado_em`), aqui **você já escolheu e fotografou a página**
antes de subir — a curadoria da fonte já aconteceu. `MaterialPage.status
= "pendente"` significa só "ainda não transcrita", não "aguardando
revisão". A etapa abaixo pode rodar direto em qualquer página pendente.

**1. Achar páginas pendentes** (fora de materiais cuja obra não existe —
não deveria acontecer, mas a query já filtra por garantia):

```bash
docker compose exec server python -c "
from sqlalchemy import select
from app.db import holder
from app.models import Material, MaterialPage, Work

with holder.SessionLocal() as session:
    rows = session.execute(
        select(MaterialPage.id, MaterialPage.material_id, Material.titulo, Work.titulo)
        .join(Material, MaterialPage.material_id == Material.id)
        .join(Work, Material.work_id == Work.id)
        .where(MaterialPage.status == 'pendente')
        .order_by(Work.id, Material.id, MaterialPage.ordem)
    ).all()
    for r in rows:
        print(r)
"
```

**2. Baixar a foto** (ela vive dentro do volume Docker, não no filesystem
do host — precisa baixar antes de ler, exatamente como `pacote.md`):

```bash
curl -s -b "$COOKIEJAR" "http://127.0.0.1:8000/materials/{material_id}/paginas/{page_id}/imagem" -o pagina.png
```

**3. Ler a foto e transcrever.** Use a ferramenta Read na `pagina.png`
baixada (lê imagem nativamente). Regras (PLANO.md, "Fotos de páginas de
livro"):

- **Transcrição literal, nunca paráfrase** — isto não é a aula editada,
  é o equivalente da transcrição bruta. Preserve a estrutura: nota de
  rodapé, citação recuada, tabela.
- Devolva **Markdown limpo** (itálico, recuo de citação onde fizer
  sentido), sem inventar o que a foto não deixa ler.
- Se a página estiver ilegível (letra miúda, tipografia antiga, sombra
  cobrindo texto), **não invente** — poste o erro em vez de um texto
  chutado (passo 4b).

**4a. Enviar a transcrição** (mesma regra de encoding do resto do
runbook — arquivo, nunca argumento inline):

```bash
WINPATH=$(cygpath -w transcricao.md)
curl -s -b "$COOKIEJAR" -X POST "http://127.0.0.1:8000/materials/{material_id}/paginas/{page_id}/colar" \
  --data-urlencode "texto@${WINPATH}"
```

Recusa com **409** se a página já tiver sido corrigida à mão
(`editado_em` preenchido) — isso é a proteção funcionando, não um bug:
não tente contornar, pule para a próxima página.

**4b. Ou marcar como erro**, se a foto não deu pra ler:

```bash
curl -s -b "$COOKIEJAR" -X POST "http://127.0.0.1:8000/materials/{material_id}/paginas/{page_id}/erro" \
  --data-urlencode "erro=letra ilegível, sombra cobrindo metade da página"
```

Uma página com erro **não trava as outras** — continue para a próxima.

**5. Validar:**

```bash
docker compose exec server python -c "
from app.db import holder
from app.models import MaterialPage
with holder.SessionLocal() as session:
    print(repr(session.get(MaterialPage, {page_id}).texto))
"
curl -s -b "$COOKIEJAR" "http://127.0.0.1:8000/works/{work_id}/ler" | grep -o "p\. [0-9]*" | head -5
```

**Atalho automatizado:** `transcrever-paginas.bat` na raiz do repo (ou o
atalho "Transcrever páginas (Estudos)" na área de trabalho) dispara isso
sozinho via `claude -p --dangerously-skip-permissions --model opus
"/transcrever-paginas"`, mesmo mecanismo de `processar-aulas.bat` —
ver `.claude/skills/transcrever-paginas/SKILL.md`.

### Fase 11 — Glossário

**Não é uma passada de IA separada.** O campo `termos` (lista de
termo/definição/citação literal/variantes) já vem na mesma resposta da
fase 6 — mesmo `colar-resposta` de sempre, mesmo `pacote.md`. O gatilho
que a IA usa é o **ato definitório** ("isso a gente chama de...",
"define-se X como...") — mera menção não conta; ver `TermDefinitionOut`
em `server/app/ai/schemas.py` pro texto completo da instrução.

Depois de colar, as propostas aparecem na tela de aprovação da aula
(`/lessons/{id}/aprovacao`), numa seção própria "Termos propostos".

**Aceitar** (`POST /lessons/{id}/termos/{proposal_id}/aceitar`, campo
`termo`) resolve ou cria o `Term` global pelo slug da grafia — mesma
regra do assunto, duas aulas propondo "Posse" e "posse" caem no mesmo
registro. Edite a grafia antes de aceitar se quiser juntar com um termo
que já existe com outro nome. As variantes que a IA propôs (`variantes`)
viram `TermAlias` automaticamente na aceitação, sem passo extra.

**Ferramentas de correção**: `/termos` lista tudo, com busca, três
ordenações (alfabética · recentes · mais definições) e um filtro
`?pendentes=1` que junta as propostas de todas as aulas num lugar só,
pra limpar em lote depois de uma semana. `/termos/{id}` é a página do
termo, com **renomear** (só o rótulo, o slug não muda), **destacar
on/off** (some do texto corrido sem sair do glossário), **variantes**
(adicionar/remover), **fundir** (escolhe outro termo, este desaparece e
tudo migra — inclusive a grafia antiga vira alias do que ficou),
**separar** um vínculo de definição pra outro termo, **editar/descartar**
uma definição sem apagar as outras do mesmo termo, e **fixar** qual
definição abre primeiro numa matéria (`TermPin`, sobrepõe a ordenação
padrão que hoje é só cronológica).

**Onde a marcação aparece:** aula editada e leitura de obra, em tempo de
renderização — nunca gravada no texto. Um termo destacado é um clique
que leva pra `/termos/{id}`; ainda não é o card sobreposto que o
PLANO.md desenha (fica pra quando essa UI existir).

**Validar:**

```bash
curl -s -b "$COOKIEJAR" "http://127.0.0.1:8000/lessons/{id}/aprovacao" | grep -o "Termos propostos ([0-9]*)"
curl -s -b "$COOKIEJAR" "http://127.0.0.1:8000/lessons/{id}/aula-editada" | grep -o "glossary-term" | head -1
```

### Fase 13 — Feynman por voz e dissertativa avaliada

**A transcrição do Feynman nunca passa por aqui.** Diferente de tudo mais
neste runbook, gravar-se explicando um termo (`/termos/{id}/feynman`) é
transcrito **automaticamente**, sempre — `faster-whisper small` rodando
na CPU da própria VPS (`server/app/media/asr.py`), não é chamada paga,
não tem ponte manual pra esse passo. Só as duas passadas de IA de
verdade (avaliar o Feynman, gerar/corrigir a dissertativa) seguem a
ponte manual de sempre.

**1. Feynman — avaliar uma explicação gravada.** Depois de gravar em
`/termos/{id}/feynman`, a página da tentativa (`/termos/{id}/feynman/{attempt_id}`)
mostra a transcrição e os botões de sempre: **Avaliar (automático)**,
**Baixar pacote (.md)**, **Colar resposta**. O pacote compara a
explicação transcrita contra **todas** as definições ativas do termo
(não uma só — "todas as definições, lado a lado" vale aqui também). Cole
a resposta em `/termos/{id}/feynman/{attempt_id}/colar-resposta`.

```bash
curl -s -b "$COOKIEJAR" "http://127.0.0.1:8000/termos/{id}/feynman/{attempt_id}/prompt.md" -o pacote.md
WINPATH=$(cygpath -w resposta.md)
curl -s -b "$COOKIEJAR" -X POST "http://127.0.0.1:8000/termos/{id}/feynman/{attempt_id}/colar-resposta" \
  --data-urlencode "resposta@${WINPATH}"
```

**2. Dissertativa — gerar a questão.** Duas fontes possíveis, cada uma
com seu próprio par pacote/colar: a partir de **uma aula**
(`/lessons/{id}/dissertativas/gerar-pacote.md` →
`/lessons/{id}/dissertativas/colar-questao`) ou a partir de **um
assunto inteiro** (`/assuntos/{id}/dissertativas/gerar-pacote.md` →
`/assuntos/{id}/dissertativas/colar-questao`, concatenando a transcrição
literal de toda aula vinculada via `context/window.py`, mesmo recorte da
fase 8a). Sempre a partir da transcrição literal, nunca da aula editada
— mesma regra do resto do app. Um assunto sem nenhuma aula aceita
vinculada não tem o que gerar (erro claro, não pacote vazio).

**3. Dissertativa — responder e corrigir.** Depois que a questão existe
(`/dissertativas/{question_id}`), responda no formulário da própria
página — isso só grava a tentativa (`status="respondido"`), sem custo
nenhum. A correção segue o mesmo par pacote/colar de sempre, agora por
tentativa: `/dissertativas/{question_id}/attempts/{attempt_id}/prompt.md`
→ `/dissertativas/{question_id}/attempts/{attempt_id}/colar-correcao`.
O histórico de tentativas fica todo na mesma página da questão — nada é
sobrescrito, cada resposta é uma linha nova.

```bash
curl -s -b "$COOKIEJAR" "http://127.0.0.1:8000/lessons/{id}/dissertativas/gerar-pacote.md" -o pacote.md
WINPATH=$(cygpath -w questao.md)
curl -s -b "$COOKIEJAR" -X POST "http://127.0.0.1:8000/lessons/{id}/dissertativas/colar-questao" \
  --data-urlencode "resposta@${WINPATH}"

curl -s -b "$COOKIEJAR" "http://127.0.0.1:8000/dissertativas/{question_id}/attempts/{attempt_id}/prompt.md" -o pacote.md
WINPATH=$(cygpath -w correcao.md)
curl -s -b "$COOKIEJAR" -X POST "http://127.0.0.1:8000/dissertativas/{question_id}/attempts/{attempt_id}/colar-correcao" \
  --data-urlencode "resposta@${WINPATH}"
```

**Validar:**

```bash
curl -s -b "$COOKIEJAR" "http://127.0.0.1:8000/termos/{id}/feynman/{attempt_id}" | grep -o "Faltou\|Nada faltando"
curl -s -b "$COOKIEJAR" "http://127.0.0.1:8000/dissertativas" | grep -o "search-results"
```

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
