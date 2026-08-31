---
name: Processar Aula
description: Processa aula(s) pendentes de IA (fase 6 em diante) seguindo o RUNBOOK.md do projeto Estudos, sem usar a API paga da Anthropic — só chamada explicitamente pelo usuário via /processar-aula.
argument-hint: [id-da-aula | pendentes]
disable-model-invocation: false
context: fork
background: true
---

Você está processando material do app "Estudos" (curso de Direito) no
papel que a API paga da Anthropic ocuparia — o usuário decidiu não usar
`ANTHROPIC_API_KEY` e fazer essa etapa manualmente, através de você.

**Primeiro passo, sempre:** leia [RUNBOOK.md](../../../RUNBOOK.md) na raiz
do repo, as seções "Por que isso funciona sem custo", "Ambiente" e
"Fase 6 — Processar aula" (e "Custo", se for conferir o registro no fim).
Não precisa ler o resto do arquivo — as demais fases ("Fluxos por fase"
além da 6) não têm nada a ver com processar aula. Ele é a fonte de
verdade de como fazer essa passada de IA. Não duplique aqui o que está
lá — siga o que estiver escrito nele, mesmo que divirja do que este
arquivo sugere, porque o runbook é atualizado a cada fase nova e este
arquivo não é.

## Alvo

`$ARGUMENTS` é o id de uma aula, ou a palavra `pendentes`. Vazio equivale
a `pendentes`.

`pendentes` significa **duas etapas, nesta ordem, nunca a segunda sem
completar a primeira** — a etapa 0 do RUNBOOK.md, seguida da etapa 1:

- **Etapa 0:** é **um script só**, não passos pra você reimplementar —
  `worker/main.py` já enfileira sozinho (via
  `POST /api/jobs/enqueue-pending-transcriptions`) e drena a fila. Rode
  `& .\worker\run_local.ps1` **em primeiro plano, nunca em background**
  (`run_in_background: false`/sem essa opção) — espere o comando em si
  retornar, não um aviso de conclusão depois. Isso é essencial em execução
  não-interativa (`claude -p`, sem sessão aberta): não existe um "turno
  seguinte" pra uma notificação de background chegar, então rodar em
  background ali abandona o job **reivindicado e travado** sem ninguém
  transcrevendo (bug real, já aconteceu: job ficou "claimed" por 15 min
  até o timeout de reivindicação obsoleta liberar de novo). Isso não é
  IA, é só o Whisper — não tem "não invente" nenhum aqui, e você não
  precisa escrever a query de novo.
- **Etapa 1:** só depois disso, aulas com transcrição **já aprovada**
  (`Transcript.aprovado_em` preenchido) e ainda sem `resumo` → processa.
  **Uma leitura só da transcrição gera tudo**: aula editada, cards,
  propostas e o guia de aula (campo `guia_md`) saem do mesmo JSON — não baixe
  nem cole nada duas vezes por aula.

**Aula com transcrição pendente de revisão humana (sem aprovar) NUNCA
entra na etapa 1** — ela fica esperando você revisar em
`/lessons/{id}/transcricao` e clicar "Aprovar transcrição". Não aprove
por conta própria, não pule essa checagem achando que "só está um pouco
atrasado".

**A matéria "LIXO" nunca entra em nenhuma das duas etapas** — nem
transcreve, nem processa, nem gera guia para aula dela.

Se `$ARGUMENTS` for um id específico, processe só aquela aula, mas ainda
assim respeitando a ordem (se ela não tem transcrição, faça a etapa 0
primeiro; se a transcrição existe mas não está aprovada, pare e diga isso
no resumo final em vez de processar mesmo assim).

## Regras não-negociáveis

1. **Sequencial, nunca paralelo.** Se houver mais de uma aula, processe
   uma de cada vez, do início ao fim, antes de começar a próxima. Múltiplas
   escritas simultâneas no SQLite local já causaram corrupção real neste
   projeto — não repita isso rodando mais de uma passada ao mesmo tempo.
2. **Não invente.** Siga a instrução central do RUNBOOK.md: todo trecho
   citado, artigo, data ou bloco da aula editada precisa vir literalmente
   da transcrição, com `start_s`/`end_s` reais.
3. **Nunca passe texto acentuado como argumento inline de curl** — nem
   `--data-urlencode "campo=$(cat arquivo)"` nem `--data-urlencode
   "campo=Usucapião"` digitado direto. As duas formas corrompem acentos
   silenciosamente (bug real, confirmado duas vezes nesta sessão, em
   campos diferentes). Sempre escreva o valor num arquivo primeiro e deixe
   o curl ler sozinho com caminho Windows: `--data-urlencode
   "campo@${WINPATH}"` (`WINPATH=$(cygpath -w arquivo)`) — vale pra
   `resposta` e pra qualquer outro campo com acento, como título de
   assunto.
4. **Confira encoding depois de qualquer POST com texto acentuado**
   (`colar-resposta`, aceitar assunto, renomear, etc). Rode o `repr()` no
   banco (comando está no RUNBOOK.md) e confirme que não apareceu `�`
   antes de considerar aquele passo concluído.
5. **Nunca aceite cards/anúncios/assuntos automaticamente.** Pare em
   `colar-resposta`. Não chame `/cards/{id}/aceitar`,
   `/cards/aceitar-todos`, `/announcements/{id}/aceitar` nem
   `/assuntos/{id}/aceitar` — isso é decisão humana, feita depois na tela
   `/aprovacao`. Sua tarefa termina quando a proposta está gravada e
   pendente de revisão.

## Ao terminar

Devolva um resumo compacto, uma linha por aula tocada — nunca a
transcrição, o prompt ou o JSON completo:

```
[etapa 0] aula 15 "Aula 3" — transcrita, aguardando sua revisão/aprovação
[etapa 1] aula 12 "Posse e propriedade" — ok — 6 blocos, 4 cards, 1 data, guia gerado, encoding ok
[etapa 1] aula 13 "Usucapião" — ok — 3 blocos, 2 cards, 0 datas, guia gerado, encoding ok
[etapa 1] aula 14 "Direitos reais" — ERRO — resposta não bateu com o schema (ver detalhe)
```

Se algo falhar numa aula, registre o erro nessa linha e continue para a
próxima — não trave o lote inteiro por causa de uma aula.
