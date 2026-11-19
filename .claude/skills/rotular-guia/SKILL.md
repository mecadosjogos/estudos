---
name: Rotular Guia
description: Passada de rótulos de formatação (Definição/Exemplo/Atenção) no guia de UMA aula ou consolidação, sem mudar nenhuma palavra, seguindo o RUNBOOK.md do projeto Estudos — chamada pelo usuário via /rotular-guia e como passo final de /consolidar-guia e /processar-aula.
argument-hint: [id-da-aula]
disable-model-invocation: false
context: fork
background: true
model: opus
---

Você está fazendo a **passada de rótulos** no guia de uma aula do app
"Estudos" (curso de Direito): acrescentar `Definição:`, `Exemplo:` e
`Atenção:` no começo dos parágrafos que são claramente isso, para o guia
ganhar os blocos com selo. **Nenhuma palavra muda.** Você aplica sozinho,
sem lista para aprovar: o que é claro entra, o que é duvidoso fica de
fora.

**Primeiro passo, sempre:** leia [RUNBOOK.md](../../../RUNBOOK.md) na
raiz do repo, a seção "Ambiente" (pra `$SERVER_URL`/`$COOKIEJAR`) e
"Rótulos do guia". As regras do que rotular e do que deixar de fora estão
no próprio pacote (baixado abaixo). Siga o pacote, não duplique aqui.

Este arquivo também é o passo final de `/consolidar-guia` e de
`/processar-aula`: quando uma delas manda "faça a passada de rótulos",
siga os passos 1–5 abaixo na mesma execução, com o id da aula que ela
acabou de gravar.

## Alvo

`$ARGUMENTS` é o id de uma aula (normal ou consolidação) que já tem guia.
Se vazio, pergunte ao usuário qual — não adivinhe, não rode em lote.
- 404: a aula não tem guia. Pare e diga isso.
- 400 "guia focado…": guia focado fica fora da passada por enquanto. Pare
  e diga isso.
- 400 "sem seções": guia antigo, de antes do guia estruturado. Pare e
  diga isso.

Rodar de novo num guia já rotulado é seguro: o que já tem rótulo fica como
está, e você só devolve o que ainda falta.

## Como fazer

1. **Baixe o pacote** para o scratchpad
   (`GET $SERVER_URL/lessons/{id}/guia/rotulos/pacote.md`). Ele traz as
   regras, o formato da resposta e cada seção do guia, aberta por
   `<<<SECAO id | título>>>`.
2. **Separe as seções em arquivos** com um script Python no scratchpad: um
   arquivo por seção (`secoes/{id}.md`, UTF-8, só o corpo) e uma cópia
   intocada (`originais/{id}.md`) para comparar no fim.
3. **Leia seção por seção e rotule com a ferramenta Edit**, nunca
   redigitando o corpo: cada mudança é um `old_string` → `new_string`
   exato (acrescentar `Definição: ` no começo do parágrafo, quebrar com
   uma linha em branco, tirar o `>` da citação, acertar asteriscos ou o
   sinal depois do rótulo). Redigitar o corpo é o jeito mais fácil de
   trocar uma palavra sem perceber, e o servidor recusa a seção inteira
   quando isso acontece. Os guias passam fácil de 100 seções — vá em
   ordem e não tente segurar o guia todo de cabeça. Na dúvida, não
   rotule.
4. **Monte a resposta** com um script: para cada seção cujo arquivo ficou
   diferente do original, a linha `<<<SECAO id | título>>>` copiada do
   pacote e o corpo inteiro. Nenhuma diferente: a resposta é `NENHUMA`.
   Envie com
   `curl -X POST $SERVER_URL/lessons/{id}/guia/rotulos/colar-resposta`
   e `--data-urlencode "resposta@${WINPATH}"`
   (`WINPATH=$(cygpath -w resposta.md)`) — nunca texto inline.
5. **Leia o JSON de volta:** `alteradas` (com o ganho de rótulos por
   seção), `rejeitadas` (com o `motivo`), `sem_mudanca`, `rotulos_antes`
   e `rotulos_depois`. Seção recusada: leia o motivo, desfaça no arquivo
   o que mudou palavra (compare com `originais/{id}.md`) e reenvie **só
   ela**. Reenviar é seguro. Se continuar recusada depois de duas
   tentativas, deixe a seção como está e conte no fim. Por último,
   baixe o pacote de novo e confirme que não apareceu `�` (encoding).

## Regras não-negociáveis

1. **Nenhuma palavra alterada, removida ou reordenada.** Só rótulo
   (Definição, Exemplo ou Atenção), quebra de parágrafo, `>` tirado,
   asteriscos e o sinal logo depois do rótulo.
2. **Na dúvida, não rotule.** Os casos duvidosos estão listados no pacote.
3. **Nunca reprocesse a aula** e nunca use `colar-resposta` da fase 6 ou
   da consolidação para isto — os dois reescrevem o guia inteiro.
4. **Nunca passe texto acentuado como argumento inline de curl.**

## Ao terminar

Devolva uma linha só (nunca o guia nem a resposta):

```
rótulos aula 66 — +32 Definição, +9 Exemplo, +64 Atenção em 41 seções — 0 recusadas
```

Se sobrou seção recusada, acrescente o número dela e o motivo, em uma
linha cada. Quando rodou sozinha (não como passo de outra skill), sugira
o próximo passo: `/dominar-guia {id}`, porque os exercícios usam os
rótulos `Definição:` e `Exemplo:`.
