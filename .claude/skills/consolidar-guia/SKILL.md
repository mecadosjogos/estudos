---
name: Consolidar Guia
description: Escreve o guia único de uma aula de consolidação juntando os guias das aulas-fonte (sem repetição, sem paráfrase de conceito, sem conteúdo externo) — inclusive o guia Focado (consolidação com foco numa prova ou tema, bloco "Foco deste guia" e selo nos temas do foco) —, seguindo o RUNBOOK.md do projeto Estudos — só chamada explicitamente pelo usuário via /consolidar-guia.
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

**Guia Focado.** Se o pacote trouxer a parte "Este guia é FOCADO", a
consolidação tem foco (uma prova ou um tema, criada em "Criar guia
focado"). Tudo o que está abaixo vale igual — o guia continua inteiro —,
mais os passos marcados **(focado)**. As regras do foco (bloco "Foco
deste guia", marca `{foco}` nos títulos, `**Atenção da professora:**`)
estão no pacote.

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

   **(focado) Itens do foco**, num segundo arquivo interno: leia a
   ORIENTAÇÃO do pacote e liste cada item — tema que cai, formato da
   prova, ponto destacado pelo professor, outra orientação —, separando
   **fala literal** (entre aspas na orientação) de **dedução** (de quem
   reuniu a orientação). Se a orientação disser de que aula veio a fala
   ("transcrição 51", "aula de 05/11"), confira cada aspa na transcrição
   dessa aula (`GET $SERVER_URL/lessons/{n}/transcricao.txt`): aspa que
   não bate com a transcrição não vai entre aspas no guia — vira
   observação, e você avisa o usuário no fim.
3. **Esqueleto temático:** monte a árvore de títulos (`##` até
   `######`, cinco níveis no máximo) na ordem que ensina melhor — não na
   ordem das aulas — e aponte cada item do inventário para um lugar. O
   que aparece em mais de uma aula vai para o MESMO lugar. A profundidade
   segue as classificações dadas em aula (gênero → espécie →
   subespécie), não um molde fixo: cada ramo desce só o que precisa, e
   nada de achatar uma espécie ao lado do seu gênero. As regras de
   montagem estão no pacote ("Como montar o índice"). Antes de redigir,
   releia o esqueleto e pergunte de cada título: "ele é espécie de algum
   irmão?" — se for, desça um nível.

   **(focado)** O foco NÃO muda o esqueleto: monte-o como se não
   houvesse foco. Só depois aponte cada tema do foco para o título mais
   alto que ele cobre inteiro (é ali que vai o `{foco}`) e cada ponto
   destacado para o trecho onde o bloco `**Atenção da professora:**`
   entra. Tema do foco sem lugar no esqueleto = sem conteúdo nos guias:
   vai para o bloco de foco como "Citado no foco, sem conteúdo nos
   guias".
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
   - **(focado)** o bloco `## Foco deste guia` vem logo depois do `#`;
     toda aspa nele e nos blocos de atenção é literal da orientação (e
     conferida na transcrição, quando dá); dedução está marcada como
     "(observação)"; nenhum conteúdo da matéria entrou no bloco; todo
     tema do foco tem `{foco}` num título ou está listado como sem
     conteúdo; nenhum filho repete a marca do pai.

   Complemente com uma conferência automática, num script Python local
   (no scratchpad): para cada frase dos guias-fonte (pulando árvore,
   sumário e trechos incompletos), normalize (caixa, acento, marcação
   markdown, espaços) e procure no guia consolidado normalizado. Liste as
   que não aparecem e revise uma a uma — cada uma tem que ser meta-fala
   removida de propósito, conteúdo que virou tabela ou repetição cortada.
   Se for conteúdo perdido, volte e coloque.
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
   - **(focado)** `foco.marcados`: os títulos que ficaram com selo, já
     numerados ("3 Direito grego"); `foco.atencao`: quantos blocos de
     atenção do professor entraram. Confira contra os itens do foco. Se
     o guia focado vier sem o bloco de foco, o POST recusa (400).
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
  `Aula 3 — Kenbet → 2.3.1 · Kenbet att → 2.3.1.2 · punições → 2.2`). É o
  que permite ao usuário conferir rápido que nada se perdeu, sem reler
  tudo. Os números seguem a regra do sistema (numeração decimal, pela
  ordem no guia): `##` = N, `###` = N.M, `####` = N.M.K e assim por
  diante — cada título é filho do título mais próximo acima dele que for
  mais raso.
- **(focado) o mapa do foco**: cada item do foco → os números onde ele
  ficou marcado (`Direito romano → 4 · "dois crimes" → atenção em
  4.2.3`); os itens **sem conteúdo nos guias** (lacunas — pode faltar
  aula ou guia); e as aspas que não bateram com a transcrição;
- o que ficou no relatório, se sobrou algo, e por quê;
- a sugestão do próximo passo: `/dominar-guia {id}` para os exercícios
  e, se o usuário quiser, `/gerar-dissertativas {id}`.

Nunca devolva o guia inteiro no chat.
