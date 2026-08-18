---
name: Processar Aula
description: Processa aula(s) pendentes de IA (fase 6 em diante) seguindo o RUNBOOK.md do projeto Estudos, sem usar a API paga da Anthropic — só chamada explicitamente pelo usuário via /processar-aula.
argument-hint: [id-da-aula | pendentes]
disable-model-invocation: true
context: fork
background: true
---

Você está processando material do app "Estudos" (curso de Direito) no
papel que a API paga da Anthropic ocuparia — o usuário decidiu não usar
`ANTHROPIC_API_KEY` e fazer essa etapa manualmente, através de você.

**Primeiro passo, sempre:** leia [RUNBOOK.md](../../../RUNBOOK.md) na raiz
do repo inteiro, incluindo a seção "Fluxos por fase". Ele é a fonte de
verdade de como fazer cada tipo de passada de IA (fase 6: processar aula;
fases futuras: o que a seção correspondente descrever quando existir). Não
duplique aqui o que está lá — siga o que estiver escrito nele, mesmo que
divirja do que este arquivo sugere, porque o runbook é atualizado a cada
fase nova e este arquivo não é.

## Alvo

`$ARGUMENTS` é o id de uma aula, ou a palavra `pendentes` (processa todas
as aulas com trabalho de IA pendente, em qualquer um dos fluxos descritos
no RUNBOOK.md — não só fase 6). Vazio equivale a `pendentes`.

## Regras não-negociáveis

1. **Sequencial, nunca paralelo.** Se houver mais de uma aula, processe
   uma de cada vez, do início ao fim, antes de começar a próxima. Múltiplas
   escritas simultâneas no SQLite local já causaram corrupção real neste
   projeto — não repita isso rodando mais de uma passada ao mesmo tempo.
2. **Não invente.** Siga a instrução central do RUNBOOK.md: todo trecho
   citado, artigo, data ou bloco da aula editada precisa vir literalmente
   da transcrição, com `start_s`/`end_s` reais.
3. **Nunca poste a resposta usando `--data-urlencode "campo=$(cat arquivo)"`.**
   Isso corrompe acentos silenciosamente (bug real, já confirmado neste
   projeto). Use sempre leitura de arquivo pelo próprio curl com caminho
   Windows (`cygpath -w`), como o RUNBOOK.md documenta.
4. **Confira encoding depois de cada `colar-resposta`.** Rode o `repr()`
   no banco (comando está no RUNBOOK.md) e confirme que não apareceu `�`
   antes de considerar aquela aula concluída.
5. **Nunca aceite cards/anúncios automaticamente.** Pare em
   `colar-resposta`. Não chame `/cards/{id}/aceitar`, `/cards/aceitar-todos`
   nem `/announcements/{id}/aceitar` — isso é decisão humana, feita depois
   na tela `/aprovacao`. Sua tarefa termina quando a proposta está gravada
   e pendente de revisão.

## Ao terminar

Devolva um resumo compacto, uma linha por aula processada — nunca a
transcrição, o prompt ou o JSON completo:

```
aula 12 "Posse e propriedade" — ok — 6 blocos, 4 cards, 1 data, encoding ok
aula 13 "Usucapião" — ok — 3 blocos, 2 cards, 0 datas, encoding ok
aula 14 "Direitos reais" — ERRO — resposta não bateu com o schema (ver detalhe)
```

Se algo falhar numa aula, registre o erro nessa linha e continue para a
próxima — não trave o lote inteiro por causa de uma aula.
