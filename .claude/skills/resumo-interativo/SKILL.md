---
name: Resumo Interativo
description: Escreve o acréscimo da página "Resumo interativo" de uma consolidação ou guia focado — resumos de 1–2 linhas dos exemplos, visuais em HTML/CSS, seções que ficam de fora, correções do mapa mental e do índice de artigos —, sem tocar no texto do guia nem trazer conteúdo externo, seguindo o RUNBOOK.md do projeto Estudos — só chamada explicitamente pelo usuário via /resumo-interativo.
argument-hint: [id-da-consolidacao]
disable-model-invocation: false
context: fork
background: true
model: opus
---

Você está escrevendo o acréscimo do **Resumo interativo** de uma
consolidação (ou guia focado) do app "Estudos" (curso de Direito). A
página interativa já existe e é montada por código, direto do guia
gravado: o texto do guia entra literal, com definições e atenções na
frente e o texto completo escondido em "ver mais", mapa mental, trilha,
busca e progresso. **Você não reescreve o guia.** Você só devolve o que o
código não tira sozinho: resumos dos exemplos, visuais, seções que ficam
de fora e correções do mapa e do índice de artigos.

**Primeiro passo, sempre:** leia [RUNBOOK.md](../../../RUNBOOK.md) na
raiz do repo, as seções "Ambiente" (pra `$SERVER_URL`/`$COOKIEJAR`) e
"Resumo interativo". As regras e o formato estão no próprio pacote
(baixado abaixo) — siga o pacote, não duplique aqui.

## Alvo

`$ARGUMENTS` é o id de uma consolidação ou guia focado que já tem guia.
Se vazio, pergunte ao usuário qual — não adivinhe, não rode em lote.
- 404: não é consolidação nem guia focado (aula normal não tem guia
  interativo). Pare e diga isso.
- 400 "sem seções": a consolidação ainda não tem guia. Pare e diga isso.

Rodar de novo é seguro: o pacote traz a "Resposta atual", e cada envio
substitui o anterior por inteiro. Parta dela e devolva o JSON completo.

## Ambiente (Windows + Git Bash)

- Exporte `MSYS_NO_PATHCONV=1` antes de passar caminhos como
  `/lessons/62/...` como argumento.
- Para escrever arquivo (JSON, script), use a ferramenta Write: `\n`
  dentro de comando Bash vira quebra de linha real e corrompe o texto.

## Como fazer (você mesmo faz o ciclo, sem pedir nada pro usuário colar)

1. **Baixe o pacote** para o scratchpad
   (`GET $SERVER_URL/lessons/{id}/guia/interativo/pacote.md`). Ele traz
   as regras, a árvore com a correspondência automática nó → tópico, o
   índice de artigos com o regex de cada entrada, e cada tópico com os
   blocos numerados por hash (`[a1b2c3d4e5 tipo] texto`). Guias de
   consolidação passam fácil de 300 mil caracteres: leia em partes,
   capítulo por capítulo, nunca só o começo.
2. **Seções de fora:** decida quais `##` não são matéria (orientações
   de estudo, avisos de prova, recados). Na dúvida, fica.
3. **Capítulo por capítulo**, escreva num arquivo de trabalho:
   - um resumo para cada exemplo narrado (bloco `ex` e os que o
     continuam), com `de`/`ate` copiados do pacote;
   - os visuais, só onde ajudam, com as classes listadas no pacote;
   - `mostrar_tudo` e `esconder_tabelas` quando couber.
4. **Mapa e artigos:** confira cada nó com `??` ou tópico errado e cada
   regex que acha demais ou de menos; corrija.
5. **Autoauditoria** antes de enviar, resumo por resumo e visual por
   visual, contra os blocos:
   - nenhum nome, número, data, artigo ou conclusão que não esteja ali;
   - o sentido não mudou ("poderá" × "deverá", "nulo" × "anulável");
   - nada deduzido "aplicando a regra" (se o guia cita seis meses, o
     visual não lista doze);
   - os selos ✔/✘ dizem exatamente o que o guia diz.
6. **Envie** com `POST $SERVER_URL/lessons/{id}/guia/interativo/colar-resposta`,
   campo `resposta` lido de arquivo (`--data-urlencode "resposta@<arquivo>"`)
   — nunca JSON acentuado inline. A resposta é um JSON:
   - `rejeitados`: item e motivo (tópico inexistente, de/ate fora do
     tópico, tag não permitida no visual…). Corrija e reenvie tudo.
   - `externos`: termos em negrito de resumos e visuais que não aparecem
     no capítulo. Confira cada um: rótulo de organização ("Pegadinha",
     "Fase jurídica — STF") pode ficar; conteúdo que não está no guia,
     não — corrija e reenvie.
   - `sem_topico_no_mapa`, `mapa` e `artigos_links`: confira o mapa e o
     índice finais.
7. **Abra a página** (`GET $SERVER_URL/lessons/{id}/guia/interativo`) e
   confira que ela responde 200 e não mostra o aviso de itens que não
   batem mais.

## Regras não-negociáveis

1. **O texto do guia não muda.** Você não o reescreve, não o corrige,
   não o completa.
2. **Resumo e visual só com o que está no guia.** Pode condensar; não
   pode acrescentar nem mudar o sentido.
3. **Na dúvida, menos.** Um visual a menos não custa nada; um visual
   errado engana quem estuda.
4. **Nunca passe texto acentuado como argumento inline de curl.**

## Ao terminar

Devolva ao usuário:

- uma linha de status:
  ```
  resumo interativo 66 — ok — 125 resumos, 35 visuais, 19 correções do mapa, 72 artigos — 1 seção de fora — 0 rejeitados
  → abra em /lessons/66/guia/interativo
  ```
- as seções que ficaram de fora e por quê;
- os `externos` que você manteve, com o motivo;
- os trechos em que nenhum visual funcionou bem, em uma linha cada.

Nunca devolva o JSON inteiro no chat.
