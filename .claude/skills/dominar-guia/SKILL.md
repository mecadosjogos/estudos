---
name: Dominar Guia
description: Gera a bateria de exercícios de memorização a partir do guia de UMA aula (não da transcrição), seguindo o RUNBOOK.md do projeto Estudos — só chamada explicitamente pelo usuário via /dominar-guia.
argument-hint: [id-da-aula]
disable-model-invocation: false
context: fork
background: true
---

Você está gerando exercícios de memorização para o app "Estudos" (curso
de Direito), a partir do GUIA de uma aula já processada — não da
transcrição. Essa passada é diferente de `/processar-aula` em dois
pontos: lê o guia (única exceção do sistema a "fonte = transcrição
literal"), e o resultado vive num sistema totalmente separado de
cards/SM-2, porque o guia já é material aceito para estudo, não a fonte
de verdade jurídica.

**Primeiro passo, sempre:** leia [RUNBOOK.md](../../../RUNBOOK.md) na
raiz do repo, a seção "Ambiente" (pra `$SERVER_URL`/`$COOKIEJAR`) e
"Dominar o guia (exercícios de memorização...)". Ele é a fonte de
verdade de como fazer essa passada — siga o que estiver escrito lá, não
duplique aqui.

## Alvo

`$ARGUMENTS` é o id de uma aula. Se vazio, pergunte ao usuário qual aula
(não adivinhe, não rode em lote — diferente de `/processar-aula`, aqui
não existe "pendentes": dominar um guia é uma decisão explícita do
usuário sobre uma aula específica).

Antes de gerar, confirme que a aula tem `guia_titulo` preenchido (guia já
existe). Se não tiver, pare e diga que a aula precisa passar por
`/processar-aula` primeiro.

## Como gerar (sem pedir nada pro usuário colar)

Diferente do resto do runbook: você mesmo faz o ciclo completo, sem
esperar o usuário copiar/colar nada.

1. `curl` em `GET $SERVER_URL/lessons/{id}/guia/exercicios-pacote.md` —
   salve como `pacote.md`.
2. Leia `pacote.md` e gere o JSON dos exercícios seguindo as instruções e
   o schema embutidos nele (os 7 tipos: definicao, cloze, lista_ordenada,
   hierarquia, discriminacao, recordacao_livre, aplicacao_caso — cubra
   vários tipos, distribuídos pelos conceitos centrais do guia, não só o
   primeiro parágrafo).
3. Escreva a resposta num arquivo (nunca argumento inline — acento
   corrompe silenciosamente, mesmo bug documentado em `/processar-aula`).
4. `curl -X POST $SERVER_URL/lessons/{id}/guia/exercicios-colar-resposta`
   com `--data-urlencode "resposta@${WINPATH}"` (`WINPATH=$(cygpath -w
   resposta.md)`).

## Regras não-negociáveis

1. **Não invente.** Trabalhe só com o que está no `guia_md` — nunca
   acrescente conhecimento jurídico externo, nunca corrija o que o guia
   diz mesmo que pareça impreciso. O objetivo é memorizar este guia
   específico.
2. **Nunca passe texto acentuado como argumento inline de curl** — mesma
   regra de `/processar-aula`: sempre escreva num arquivo primeiro.
3. **Nunca aceite os exercícios automaticamente.** Pare depois de colar a
   resposta — não chame `/exercicios/{id}/aceitar` nem
   `/exercicios-aceitar-todos`. Aprovação é decisão humana, feita depois
   em `/lessons/{id}/guia/exercicios-aprovacao`.
4. **Confira encoding** depois do POST (mesmo `repr()` no banco descrito
   no RUNBOOK para `/processar-aula`) se houver texto acentuado.

## Ao terminar

Devolva um resumo compacto: quantos exercícios de cada tipo foram
gerados, e o link para a tela de aprovação. Nunca a transcrição, o guia
inteiro ou o JSON completo.

```
aula 12 "Posse e propriedade" — ok — 3 definição, 2 cloze, 1 lista, 1 hierarquia, 2 discriminação, 1 recordação livre, 1 aplicação de caso
→ revise em /lessons/12/guia/exercicios-aprovacao
```
