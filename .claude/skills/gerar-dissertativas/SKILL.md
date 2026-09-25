---
name: Gerar Dissertativas
description: Gera um lote de questões dissertativas (com rubrica, pistas e resposta certa) a partir do guia de UMA aula, para o banco de treino do projeto Estudos, seguindo o RUNBOOK.md — só chamada explicitamente pelo usuário via /gerar-dissertativas.
argument-hint: [id-da-aula] [quantidade]
disable-model-invocation: false
context: fork
background: true
---

Você está criando questões dissertativas para o app "Estudos" (curso de
Direito), a partir do GUIA de uma aula já processada. **Isto só roda
quando o usuário pede.** No dia a dia, quem gera questão é a IA local da
máquina com GPU; este lote existe para quando o usuário quer questões de
qualidade maior no banco. A correção continua sempre na IA local, com a
resposta certa que você escrever servindo de referência para ela.

**Primeiro passo, sempre:** leia [RUNBOOK.md](../../../RUNBOOK.md) na raiz
do repo, as seções "Ambiente" (pra `$SERVER_URL`/`$COOKIEJAR`) e "IA local —
dissertativas". Siga o que estiver escrito lá; não duplique aqui.

## Alvo

`$ARGUMENTS` é `<id-da-aula> [quantidade]`. A quantidade padrão é 5 e o
máximo é 15. Se o id estiver vazio, pergunte ao usuário qual aula: não
adivinhe e não rode em lote de aulas.

## Como gerar (ciclo completo, sem pedir nada pro usuário colar)

1. `curl -s -b "$COOKIEJAR" "$SERVER_URL/lessons/{id}/dissertativas/pacote-claude.md?n={quantidade}" -o pacote.md`.
   Se a resposta for um erro 400 ("sem guia estruturado"), pare e diga que a aula precisa passar por `/processar-aula` primeiro.
2. Leia `pacote.md` inteiro: instruções, guia completo, questões que já
   existem, cobertura por seção e schema. Gere o JSON do lote seguindo
   **exatamente** as regras dele. Pontos de atenção, que são o que a
   bancada de qualidade pegou nos modelos locais:
   - o `criterio_texto` **nunca** nomeia o conceito que responde à
     questão (o servidor troca por uma instrução genérica se nomear);
   - a rubrica usa só o que está no material, com cada ponto verificável
     em sim/não, e o `secao` de cada ponto é uma das `secoes` da questão;
   - a `pista` orienta sem entregar;
   - a `resposta_modelo` cobre **todos** os pontos da rubrica, só com
     conteúdo do material, no tamanho de uma resposta de prova. É ela que
     a IA local usa como referência para corrigir, então precisa estar
     certa;
   - espalhe as questões por seções diferentes, priorizando as que têm
     menos questões, e não repita as existentes.
3. Escreva o JSON num arquivo (`lote.json`), nunca como argumento inline:
   acento corrompe silenciosamente, o mesmo bug documentado em
   `/processar-aula`.
4. `curl -s -b "$COOKIEJAR" -X POST "$SERVER_URL/lessons/{id}/dissertativas/importar" -H "Content-Type: application/json; charset=utf-8" --data-binary "@lote.json"`.
   A resposta traz os ids e enunciados gravados. Um erro 400 diz qual
   questão não validou (é tudo ou nada): corrija e reenvie.
5. Informe ao usuário quantas questões entraram e de quais seções.
