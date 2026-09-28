---
name: Consolidar Guia
description: Escreve o guia único de uma aula de consolidação juntando os guias das aulas-fonte (sem repetição, sem paráfrase de conceito, sem conteúdo externo), seguindo o RUNBOOK.md do projeto Estudos — só chamada explicitamente pelo usuário via /consolidar-guia.
argument-hint: [id-da-consolidação]
disable-model-invocation: false
context: fork
background: true
model: opus
---

Você está escrevendo o GUIA CONSOLIDADO de uma matéria do app "Estudos"
(curso de Direito): os guias de várias aulas viram um guia único, para
estudar depois que a matéria fechou. Quem lê precisa achar tudo o que foi
dado em aula, uma vez só, organizado para aprender — e com as palavras
com que cada conceito foi dado, porque é isso que cai na prova.

**Primeiro passo, sempre:** leia [RUNBOOK.md](../../../RUNBOOK.md) na
raiz do repo, a seção "Ambiente" (pra `$SERVER_URL`/`$COOKIEJAR`) e
"Consolidação de guias". As regras de conteúdo e o formato de saída estão
no próprio pacote (baixado abaixo) — siga o pacote, não duplique aqui.

## Alvo

`$ARGUMENTS` é o id de uma aula de consolidação (criada na tela da
matéria, "Consolidar aulas"). Se vazio, pergunte ao usuário qual — não
adivinhe, não rode em lote. Se `GET /lessons/{id}/consolidacao/pacote.md`
der 404, a aula não é uma consolidação: pare e diga isso.

Rodar de novo numa consolidação que já tem guia reescreve o guia inteiro.

## Como fazer (você mesmo faz o ciclo, sem pedir nada pro usuário colar)

1. **Baixe o pacote** para um arquivo no scratchpad
   (`GET $SERVER_URL/lessons/{id}/consolidacao/pacote.md`). Ele traz as
   regras, o formato e os guias-fonte em ordem cronológica.
2. **Inventário** (arquivo interno, nunca vai pro guia): percorra cada
   guia-fonte e liste cada conceito, definição, classificação, lista,
   fato, data, nome e exemplo que ele traz, com a aula de onde veio. É o
   checklist do "nada se perde". Os guias passam fácil de 100 mil
   caracteres juntos — trabalhe guia por guia, não tente segurar tudo de
   cabeça.
3. **Esqueleto temático:** monte a árvore `##` (tema) / `###`
   (subtítulo) / `####` (conceito) na ordem que ensina melhor — não na
   ordem das aulas — e aponte cada item do inventário para um lugar. O
   que aparece em mais de uma aula vai para o MESMO lugar. Cada conceito
   que alguém procuraria no índice merece o seu `####`.
4. **Redija seção por seção** no arquivo de saída (um `##` por vez,
   acrescentando ao arquivo), copiando a redação dos guias. Juntar,
   mover, cortar a repetição, montar tabela ou lista: pode. Trocar a
   palavra de um conceito, "melhorar" a frase, acrescentar explicação
   sua: não.
5. **Autoauditoria** contra o inventário, antes de enviar:
   - todo item do inventário está no guia (marque um por um);
   - nenhuma definição/conceito ficou com redação diferente da do guia;
   - nada de fora dos guias entrou (autor, data, exemplo, explicação);
   - não sobrou meta-fala de aula ("retomada", "na aula passada") nem
     indicação de aula de origem;
   - não há números nos títulos nem sumário/índice (o sistema gera).
6. **Envie** com `curl -X POST $SERVER_URL/lessons/{id}/consolidacao/colar-resposta`
   e `--data-urlencode "resposta@${WINPATH}"` (`WINPATH=$(cygpath -w guia.md)`)
   — nunca texto inline. A resposta é um JSON com `secoes`, `subtitulos`,
   `conceitos` e `relatorio`:
   - `relatorio.perdidos`: termos em negrito das fontes que não aparecem
     no consolidado. Confira cada um: se foi perda, corrija e reenvie; se
     o termo está lá com outra grafia/forma (ex.: virou célula de
     tabela), está ok.
   - `relatorio.externos`: termos em negrito do consolidado que não estão
     em nenhuma fonte. Quase sempre é conteúdo externo ou paráfrase —
     corrija e reenvie. Só fica se for título/rótulo de organização.
   Reenviar é seguro: cada envio substitui o guia inteiro.
7. **Confira o encoding** no banco (`repr()` de um trecho acentuado de
   `lesson.guia_md`, mesmo procedimento do RUNBOOK para `/processar-aula`).

## Regras não-negociáveis

1. **Não invente e não parafraseie conceito.** O limite é o que está nos
   guias; a redação dos conceitos é a do guia.
2. **Não perca conteúdo.** Detalhes complementares de aulas diferentes se
   somam; versões divergentes ficam lado a lado, sem você resolver.
3. **Sem aula de origem no texto.** O consolidado é um texto só.
4. **Nunca passe texto acentuado como argumento inline de curl.**

## Ao terminar

Devolva ao usuário:

- uma linha de status:
  ```
  consolidação 40 "Consolidação aulas 01/07 até 28/09" — ok — 9 temas, 31 subtítulos, 74 conceitos — relatório: 0 perdidos, 0 externos
  → leia em /lessons/40/guia
  ```
- **o inventário final, compacto**: para cada aula-fonte, a lista dos
  conceitos dela com o número onde cada um foi parar no guia novo (ex.:
  `Aula 3 — Kenbet → 2.3a · Kenbet att → 2.3b · punições → 2.2`). É o que
  permite ao usuário conferir rápido que nada se perdeu, sem reler tudo.
  Os números seguem a regra do sistema: `##` = N, `###` = N.M, `####` =
  N.M + letra, contando pela ordem no guia.
- o que ficou no relatório, se sobrou algo, e por quê;
- a sugestão do próximo passo: `/dominar-guia {id}` para os exercícios
  e, se o usuário quiser, `/gerar-dissertativas {id}`.

Nunca devolva o guia inteiro no chat.
