---
name: Guia Focado
description: Escreve o guia de um guia Focado — só o conteúdo de uma prova ou tema, tirado dos guias das aulas-fonte (sem paráfrase de conceito, sem conteúdo externo, sem perder nada do foco), com o bloco "Foco deste guia" no topo, seguindo o RUNBOOK.md do projeto Estudos — só chamada explicitamente pelo usuário via /guia-focado.
argument-hint: [id-do-guia-focado]
disable-model-invocation: false
context: fork
background: true
model: opus
---

Você está escrevendo um GUIA FOCADO do app "Estudos" (curso de Direito):
dos guias de várias aulas de uma matéria sai um guia **só com o conteúdo
do foco** — uma prova ("o que cai na P1") ou um tema. Quem pega o guia
quer estudar exatamente aquilo, sem o resto da matéria no caminho, e com
as palavras com que cada conceito foi dado em aula, porque é isso que cai
na prova.

**É outra feature, não a consolidação.** A consolidação (`/consolidar-guia`)
junta a matéria inteira; o guia focado recorta o foco. Não use a skill
de consolidação para um guia focado, nem esta para uma consolidação.

**Primeiro passo, sempre:** leia [RUNBOOK.md](../../../RUNBOOK.md) na
raiz do repo, as seções "Ambiente" (pra `$SERVER_URL`/`$COOKIEJAR`) e
"Guia Focado". As regras de conteúdo e o formato de saída estão no
próprio pacote (baixado abaixo) — siga o pacote, não duplique aqui.

## Alvo

`$ARGUMENTS` é o id de um guia focado (criado na tela da matéria, "Criar
guia focado"). Se vazio, pergunte ao usuário qual — não adivinhe, não
rode em lote. Baixe o pacote: se der 404, não é uma aula de consolidação;
se o pacote NÃO trouxer a parte "Este guia é FOCADO", é uma consolidação
comum — nos dois casos pare e diga isso ao usuário.

Rodar de novo num guia focado que já tem guia reescreve o guia inteiro.

## Ambiente (Windows + Git Bash)

- Exporte `MSYS_NO_PATHCONV=1` antes de passar caminhos como
  `/lessons/62/...` como argumento — senão o Git Bash os converte em
  caminho do Windows e tudo volta 404.
- Para escrever arquivo (guia, script), use a ferramenta Write: `\n`
  dentro de comando Bash vira quebra de linha real e corrompe o texto.

## Como fazer (você mesmo faz o ciclo, sem pedir nada pro usuário colar)

1. **Baixe o pacote** para um arquivo no scratchpad
   (`GET $SERVER_URL/lessons/{id}/consolidacao/pacote.md`). Ele traz as
   regras, a parte "Este guia é FOCADO", a ORIENTAÇÃO do usuário e os
   guias-fonte em ordem cronológica.
2. **Itens do foco** (arquivo interno): leia a ORIENTAÇÃO e liste cada
   item — tema que cai, formato da prova, ponto destacado pelo professor,
   outra orientação —, separando **fala literal** (entre aspas na
   orientação) de **dedução** (de quem reuniu a orientação). Se a
   orientação disser de que aula veio a fala ("transcrição 51", "aula de
   05/11"), confira cada aspa na transcrição dessa aula
   (`GET $SERVER_URL/lessons/{n}/transcricao.txt`): aspa que não bate não
   vai entre aspas — vira observação, e você avisa o usuário no fim.
3. **Inventário com recorte** (arquivo interno, nunca vai pro guia):
   percorra cada guia-fonte e liste cada conceito, definição,
   classificação, lista, fato, data, nome e exemplo, com a aula de onde
   veio e uma marca: **DENTRO** (pertence a um tema do foco), **FORA** ou
   **FRONTEIRA** (conceito de fora ensinado dentro de um tema do foco, ou
   dúvida). O critério é o TEMA, não a aula. Os guias passam fácil de
   100 mil caracteres juntos — trabalhe guia por guia.
   - Orientação sobre ESTA prova que esteja num guia-fonte (ex.: uma
     seção "Orientações para a prova") vai para o bloco de foco.
   - Avisos de OUTRA prova ficam FORA.
4. **Esqueleto temático** só com o que é DENTRO (e FRONTEIRA que você
   decidir incluir, pela regra do pacote): árvore de títulos (`##` até
   `######`, cinco níveis no máximo) na ordem que ensina melhor — não na
   ordem das aulas. O que aparece em mais de uma aula vai para o MESMO
   lugar. A profundidade segue as classificações dadas em aula (gênero →
   espécie → subespécie); as regras de montagem estão no pacote ("Como
   montar o índice"). Antes de redigir, pergunte de cada título: "ele é
   espécie de algum irmão?" — se for, desça um nível. Aponte cada ponto
   destacado pelo professor para o trecho onde o bloco
   `**Atenção da professora:**` entra.
5. **Redija** o arquivo de saída: primeiro o `#` título e o bloco
   `## Foco deste guia` (regras no pacote, inclusive a linha "ficou de
   fora"), depois a árvore e as seções, uma `##` por vez, copiando a
   redação dos guias. Juntar, mover, cortar a repetição, montar tabela
   ou lista: pode. Trocar a palavra de um conceito, "melhorar" a frase,
   acrescentar explicação sua: não. Sem `{foco}` nos títulos.
6. **Autoauditoria** antes de enviar:
   - todo item DENTRO do inventário está no guia (marque um por um);
   - nenhum item FORA entrou;
   - nenhuma definição/conceito ficou com redação diferente da do guia;
   - nada de fora dos guias entrou (autor, data, exemplo, explicação);
   - não sobrou meta-fala de aula ("retomada", "na aula passada") nem
     indicação de aula de origem;
   - não há números nos títulos nem sumário/índice (o sistema gera);
   - o bloco de foco: aspas literais da orientação (conferidas quando
     dá), dedução marcada "(observação)", nenhum conteúdo da matéria,
     linha "ficou de fora" presente; blocos de atenção em parágrafo
     próprio (linha em branco antes).

   Complemente com uma conferência automática, num script Python local:
   para cada frase dos guias-fonte, normalize (caixa, acento, marcação,
   espaços) e procure no guia normalizado. Revise as que não aparecem:
   cada uma tem que ser FORA do foco, meta-fala removida, conteúdo que
   virou tabela ou repetição cortada. Se for DENTRO e sumiu, volte e
   coloque.
7. **Envie** com `POST $SERVER_URL/lessons/{id}/consolidacao/colar-resposta`,
   campo `resposta` lido de arquivo — nunca texto acentuado inline. A
   resposta é um JSON:
   - `relatorio.perdidos`: termos em negrito das fontes que não aparecem
     no guia. **Num guia focado a maioria é esperada** (é o que ficou
     FORA). Confira cada um contra o inventário: se é DENTRO, foi perda —
     corrija e reenvie.
   - `relatorio.externos`: termos em negrito do guia que não estão em
     nenhuma fonte. Quase sempre é conteúdo externo ou paráfrase —
     corrija e reenvie. Só fica se for título/rótulo de organização.
   - `foco.atencao`: quantos blocos de atenção do professor viraram bloco.
   - Guia focado sem o bloco de foco é recusado (400).
   Reenviar é seguro: cada envio substitui o guia inteiro.
8. **Confira o encoding** no banco (`GET /lessons/{id}/guia.md`, acentos
   corretos, sem mojibake).

## Regras não-negociáveis

1. **Só o foco.** O que não pertence aos temas do foco não entra.
2. **Dentro do foco, nada se perde.** Detalhes complementares de aulas
   diferentes se somam; versões divergentes ficam lado a lado, sem você
   resolver.
3. **Não invente e não parafraseie conceito.** O limite é o que está nos
   guias; a redação dos conceitos é a do guia.
4. **Sem aula de origem no texto.**
5. **Fala do professor só entre aspas quando literal.**
6. **Nunca passe texto acentuado como argumento inline de curl.**

## Ao terminar

Devolva ao usuário:

- uma linha de status:
  ```
  guia focado 62 "Focado — Prova" — ok — 4 temas, 31 subtítulos, 40 conceitos — relatório: 0 externos — 1 bloco de atenção
  → leia em /lessons/62/guia
  ```
- **o mapa do foco**: cada item do foco → os números onde ele ficou no
  guia; itens **sem conteúdo nos guias** (lacunas); aspas que não
  bateram com a transcrição;
- **o que ficou de fora**, em uma linha por aula-fonte (ex.: `Aula 3 —
  Egito, lei mosaica, Código de Manu: fora`), e **os casos de
  FRONTEIRA** com a decisão tomada, para o usuário confirmar;
- divergências entre aulas mantidas lado a lado;
- a sugestão do próximo passo: `/dominar-guia {id}` e, se quiser,
  `/gerar-dissertativas {id}`.

Nunca devolva o guia inteiro no chat.
