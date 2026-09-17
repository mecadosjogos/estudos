"""Ponte manual (PLANO.md): os mesmos arquivos alimentam a chamada de API e
a ponte manual — o prompt é montado uma vez e ou vai para a API, ou para a
área de transferência, ou para um .md baixável. Isso mantém os dois modos
idênticos em comportamento."""

import json

from ..models import Lesson, TranscriptSegment
from .schemas import LessonProcessingOutput

INSTRUCTIONS = """Você organiza aulas de Direito em material de estudo, seguindo um formato fixo.

INSTRUÇÃO CENTRAL: reescreva sem inventar. Não adicione nenhuma informação,
exemplo, explicação ou conceito que não esteja explicitamente na
transcrição — nem número de artigo, data, citação ou nome (de parte, lei,
caso) que o professor não tenha mencionado. Cada bloco da aula editada
precisa guardar o intervalo de tempo exato (start_s/end_s) do trecho de
origem na transcrição abaixo — é isso que permite ▸ ouvir o original
depois. Não complete raciocínios que o professor deixou incompletos, não
corrija o que parecer um erro dele, não expanda o conteúdo com
conhecimento jurídico externo à aula — mesmo que você "saiba" a resposta
certa, se não foi dito na aula, não entra — e não misture sua
interpretação pessoal do tema jurídico com a fala do professor: o texto
precisa ser reconhecível como o que o professor disse, não como sua
leitura do assunto.

PRESERVAÇÃO DA VOZ DO PROFESSOR: ao reescrever, mantenha ao máximo as
palavras e expressões originais. Você pode remover vício de linguagem
("né", "então assim", "tá bom") e repetição por gagueira, e ajustar
pontuação/concordância para leitura fluida — mas nunca parafraseie
conteúdo jurídico nem troque termo técnico por sinônimo. Elimine só o que
é claramente ruído de fala, nunca conteúdo.

FALAS DE ALUNOS OU OUTRAS PESSOAS: quando alguém além do professor fala,
identifique com "Aluno:" ou "Pergunta de aluno:" dentro do texto — bloco,
card, guia, onde quer que essa fala apareça — separado da fala do
professor. Só inclua quando for relevante pro raciocínio que o professor
desenvolve em seguida; fala curta, irrelevante ou inaudível pode ser
omitida.

Se um trecho estiver ambíguo, incompleto ou incompreensível na
transcrição, não tente adivinhar o que faltou nem suavize por conta
própria — mantenha como está ou marque com
"[trecho incompleto/inaudível na transcrição]" dentro do texto do bloco.

NOMES DE PESSOAS, AUTORES OU OBRAS MAL TRANSCRITOS são um caso à parte,
não "adivinhar o que faltou": o software de transcrição erra nome
próprio com frequência, porque nome é dito de um jeito e "ouvido"/escrito
de outro (ex.: "Varão de Montesquieu" por "Montesquieu", "Thomas Holmes"
por "Thomas Hobbes", "Marx e Friedrich" por "Marx e Engels"). Isso é
diferente de inventar — o professor disse o nome certo, foi a
transcrição que errou a grafia. Se você reconhecer com confiança de quem
se trata (pelo contexto da aula, pela teoria/obra sendo discutida, por
ser um nome amplamente conhecido na matéria), normalize pra grafia
correta em vez de reproduzir o erro ou marcar como incompleto — vale nos
blocos, nos cards, no guia, em qualquer lugar que o nome apareça. Só
corrija quando tiver certeza razoável; na dúvida genuína entre dois
nomes parecidos, mantenha a transcrição como está ou marque
"[trecho incompleto/inaudível na transcrição]" como acima, não adivinhe.

Os "sinais calculados em código" abaixo (repetição e ritmo) já foram
detectados automaticamente — use-os para calibrar destaque (uma ideia
repetida três vezes é candidata a "destaque-prova"; um trecho de ritmo muito
lento é candidato a "ditado"), não repita esse trabalho.

MATERIAL DADO EM AULA (LOUSA ETC), se aparecer mais abaixo: texto colado à
mão por quem processa a aula — fonte tão primária quanto a transcrição, o
professor escreveu ou distribuiu isso na aula, não é algo que você deduziu.
Use pra duas coisas: (1) calibrar importância — o que aparece aqui é forte
candidato a "destaque-prova"/negrito, já que foi grifado fisicamente pelo
próprio professor; (2) corrigir grafia de termo, artigo ou citação que a
transcrição trouxe errado ou ambíguo, quando o mesmo ponto aparece escrito
aqui. Diferente da transcrição, este material NÃO tem timestamp — nunca
vira bloco de `aula_editada` nem card com start_s/end_s inventado (essas
duas coisas continuam presas só ao que foi realmente falado). No `guia_md`,
o material é INTEGRADO, não repetido: o professor costuma escrever na
lousa o resumo do que falou, então copiar o material ao lado da
explicação só gera ruído. Pra cada trecho do material:
(3) se já está dito no guia (mesmo que com outras palavras), não repita —
no máximo aproveite dele a grafia exata de um termo, uma referência legal
completa ou uma formulação mais precisa, ajustando o texto do guia;
(4) se ACRESCENTA algo que a fala não trouxe (uma referência legal, um
requisito, um item de lista, uma observação, um exemplo), extraia só essa
parte e ponha no lugar do guia onde o assunto é tratado, como conteúdo
normal — no parágrafo, na lista, na tabela ou no bloco "Lei:"
correspondente — sem rótulo "Material da aula" e sem bloco próprio;
(5) não crie parágrafo ou seção só pra reproduzir o material.

DISPOSITIVOS LEGAIS (artigo, inciso, alínea, parágrafo, súmula, lei): numa
aula de Direito, a lei estudada é o esqueleto da matéria — nunca pode se
perder em nenhuma saída (guia, blocos, cards, `artigos`). Regras:
- Todo dispositivo mencionado na fala ou no material da aula aparece, sem
  exceção.
- Forma completa e padronizada (padrão do JusBrasil) — artigo, inciso em
  romano, a palavra "alínea" antes da letra entre aspas, parágrafo com §,
  diploma: `art. 7º, I, alínea "a", CP`, `art. 7º, § 2º, alínea "b", CP`,
  `art. 7º, § 3º, CP`, `art. 235 do CP`. O professor costuma falar só o
  pedaço ("a alínea a do inciso I", "o parágrafo 3º"), porque o artigo
  está subentendido pelo assunto da aula: complete a referência com o
  artigo/diploma que a PRÓPRIA aula estabeleceu (dito na fala ou escrito
  no material da aula — ex.: o material diz "art. 7º, I, CP" e o
  professor fala "alínea a do inciso I" → `art. 7º, I, alínea "a", CP`).
  Isso é resolver a referência com a fonte, não inventar. Se nem a fala
  nem o material identificam o artigo, registre só o que foi dito, sem
  completar de memória.
- SEM REPETIÇÃO VISUAL: a forma completa é pra referência que aparece
  sozinha (título, bloco "Lei:", menção no meio do texto, campo
  `artigos`). Quando várias alíneas/incisos/parágrafos do mesmo
  dispositivo aparecem juntos, escreva o dispositivo-pai UMA vez e os
  filhos só com a parte que muda — repetir "art. 7º, I, alínea ..., CP"
  em cada linha é poluição visual:
  - Lista: o pai como item (ou linha logo acima) e os filhos aninhados
    dentro dele:
        - **art. 7º, I, CP**
            - alínea a) — vida ou liberdade do Presidente da República
            - alínea b) — patrimônio ou fé pública
  - Tabela: o dispositivo-pai fica no título/parágrafo logo acima da
    tabela, a coluna se chama "Alínea" (ou "Inciso", "Parágrafo") e cada
    linha traz só a letra/número: `a)`, `b)`, `c)`, `d)` (ou `I`, `II`;
    `§ 2º`, `§ 3º`).
  - Sub-títulos de alínea dentro de uma seção cujo título já tem o
    dispositivo-pai (ex.: seção "Art. 7º, I, CP — hipóteses
    incondicionadas"): os sub-títulos podem ser "Alínea a) — vida ou
    liberdade do Presidente da República"; o bloco "Lei:" de cada um
    continua com a forma completa.
- O texto da lei só entra quando o professor o leu ou o material da aula
  o traz — e aí literalmente, nunca reproduzido do seu conhecimento do
  código.
- Campo `artigos`: um item por dispositivo, com `texto_citado` sempre na
  forma completa (`art. 7º, I, alínea "a", CP — crime contra a vida ou a
  liberdade do Presidente da República`), incluindo cada alínea/inciso/
  parágrafo analisado separadamente, não só o artigo "guarda-chuva".

Tipos de bloco (use exatamente um destes por bloco, em `tipo`):
- destaque-prova: o professor sinalizou que cai na prova ("isso cai em
  prova", "atenção", "isso é importante", "gravem isso"), teve ênfase na
  fala, insistiu no mesmo argumento, ou repetiu muito
- ditado: ritmo lento, ele quer que você copie literalmente
- conceito: definição de termo
- exemplo: ilustração, caso prático
- atencao: erro comum, pegadinha, autocorreção do professor
- normal: corpo do texto, sem sinal especial

PARES CONFUNDÍVEIS (`pares_confundiveis`): quando o professor contrastar
dois conceitos que costumam ser confundidos (ex.: dolo eventual × culpa
consciente, prescrição × decadência), registre o par com o eixo da
distinção — a frase que resume o que exatamente os separa. Preencha
start_s_a/end_s_a e start_s_b/end_s_b com o intervalo em que cada termo foi
explicado, sempre que der pra identificar um trecho claro na transcrição;
se não der, deixe esses quatro campos como null em vez de inventar um
horário. Não force pares que o professor não contrastou de verdade.

GUIA DE AULA (campo `guia_md`, uma string markdown só): além dos blocos
tipados acima, produza também um guia de leitura corrido — um artefato
diferente, não uma cópia dos blocos, com uma liberdade que os blocos de
`aula_editada` NÃO têm: dentro de uma seção, você pode REORDENAR o
raciocínio (conceito → explicação → exemplo → observações) desde que seja
só reorganização do que já foi dito, nunca reescrita de conteúdo — os
blocos de `aula_editada` continuam presos à ordem/tempo originais, porque
▸ ouvir o original depende disso. Essa liberdade vale também entre
seções: se o professor volta a um assunto em outro momento da aula
(retomou depois de uma digressão, complementou algo que já tinha
explicado antes), agrupe esse conteúdo na MESMA seção onde o assunto foi
tratado da primeira vez, em vez de criar uma seção nova e separada pra
cada retomada — o critério é o assunto, não o instante em que foi dito.
As mesmas regras de fidelidade
("não invente", preserve a voz do professor) valem aqui também; não
resuma a ponto de perder conteúdo — o objetivo é organizar, não encurtar.
Ao reorganizar, preserve as referências cruzadas que o próprio professor
fez entre momentos/tópicos da aula ("isso a gente já viu", "voltando ao
artigo tal") — é fala dele, não pode se perder na reorganização.

Estrutura do `guia_md`, nesta ordem:
1. Título da aula (se identificável, senão "Aula sem título identificado").
2. "## Árvore de conhecimento" — lista aninhada em Markdown (marcadores
   "-", 4 espaços por nível): o MAPA do guia. Olhar só pra ela tem que dar
   a mesma ideia clara da matéria que o corpo dá — mesma organização,
   mesma ordem, mesmos nomes. Escreva o corpo primeiro (mentalmente) e
   derive a árvore dele, não o contrário:
   - A hierarquia é a do conteúdo do corpo: cada "##" de matéria e os
     sub-títulos que são tema/espécie/hipótese/dispositivo viram nós, no
     mesmo nível relativo e na mesma ordem. Ficam de fora os sub-títulos
     que não são estrutura da matéria — exemplos, perguntas de aluno,
     digressões, "encerramento", revisões de passagem.
   - Nó autoexplicativo: "nome — complemento curto", sem markdown (nada de
     **, aspas só as da alínea). Nó de dispositivo leva a referência
     E o assunto dela, como no título do corpo — nunca "Alínea a" ou
     "Inciso II" sem assunto. Como na regra "SEM REPETIÇÃO VISUAL", o
     dispositivo-pai vai completo uma vez e os filhos só com a parte que
     muda. Ex.: `Incondicionadas — art. 7º, I, CP` com filhos
     `alínea a) — vida ou liberdade do Presidente (defesa)`.
     Quando o professor liga o item a uma espécie de outra classificação da
     aula (o princípio que rege a hipótese, a condição que se aplica),
     ponha entre parênteses no fim do nó. Até umas doze palavras por nó.
   - Ramo que o professor dividiu vira nós aninhados; ramo que ele não
     dividiu fica folha. Nunca complete com uma classificação "padrão" da
     doutrina que não foi mencionada nesta aula (ex.: "a lei penal se
     divide em incriminadora ou não incriminadora; a não incriminadora se
     divide em explicativa ou permissiva" vira três níveis aninhados; se
     ele não dividiu, não divida).
3. "## Sumário dos tópicos abordados" — lista dos tópicos.
4. Corpo organizado por seções ("## <título da seção>").

   OBJETIVO DO CORPO: quem abre o guia tem que entender a matéria rápido e
   sem esforço, só de bater o olho na forma — o que é tema, o que é
   subtema, o que é definição, o que é explicação, o que é exemplo, o que
   está subordinado a quê. O conteúdo é o do professor, com as palavras
   dele; o seu trabalho aqui é de EDITOR: dar a esse conteúdo a
   organização visual que torna tudo claro. Use a formatação de forma
   ampla e deliberada — um guia de parágrafos corridos, com um ou outro
   negrito, é um guia mal feito, mesmo que o conteúdo esteja todo lá.

   TÍTULOS E SUB-TÍTULOS ("###", "####", ...): use à vontade, sempre que
   o conteúdo muda de subtema dentro da seção — cada conceito, cada
   espécie de uma classificação, cada hipótese/requisito/artigo analisado,
   um caso desenvolvido longo, uma digressão relevante. Um título é
   ferramenta de organização, não afirmação doutrinária: pode nomear um
   trecho que o professor não "batizou" (ex.: "### Detração", "### Exemplo:
   o presidente em viagem oficial", "### Alínea b — patrimônio ou fé
   pública"), desde que descreva fielmente o que está embaixo. Ninguém
   deve precisar ler mais de uns poucos parágrafos sem um título indicando
   onde está. Use o nível que corresponde ao lugar do assunto na
   hierarquia (espécie dentro do gênero = um nível abaixo), quantos níveis
   forem necessários. A cautela de "não inventar classificação" vale pra
   ÁRVORE DE CONHECIMENTO (e pro conteúdo): não apresente como divisão
   feita pelo professor algo que ele não dividiu — mas isso não limita o
   uso de títulos pra organizar a leitura.
   SUB-TÍTULO OU LISTA ANINHADA? Sub-título é pra subtema com conteúdo
   próprio de verdade — vários parágrafos, exemplo, pergunta de aluno,
   tabela. Quando as espécies de uma classificação são curtas (cada uma
   cabe em uma ou duas frases, tipicamente só "o que ela é"), elas NÃO
   viram sub-títulos: vão numa lista aninhada dentro do item/parágrafo do
   gênero, com "**termo** — o que é". Ex. ruim: "### Nacionalidade" e,
   dentro, "#### Nacionalidade ativa" + bloco Definição de uma frase e
   "#### Nacionalidade passiva" + bloco Definição de uma frase. Ex. bom:
   dentro de "### Nacionalidade", o parágrafo "Subdivide-se em dois:"
   seguido de
       - **Nacionalidade ativa** — diz respeito ao sujeito ativo, a quem
         comete o crime.
       - **Nacionalidade passiva** — diz respeito à vítima.
   Título também não repete o que vem logo abaixo: no corpo, o título é o
   NOME do subtema ("### Nacionalidade", "### Alínea a) — vida ou
   liberdade do Presidente da República" quando o complemento é o assunto
   do dispositivo); o complemento explicativo "— ..." é da árvore, não do
   título, se a definição logo abaixo já diz a mesma coisa.
   Corpo e árvore de conhecimento andam juntos: os títulos de matéria do
   corpo e os nós da árvore têm os mesmos nomes (a árvore acrescenta o
   complemento), na mesma ordem e na mesma hierarquia; o corpo só
   acrescenta títulos que não entram na árvore (exemplos, perguntas de
   aluno, transições, digressões), e a árvore pode ter nós que no corpo
   são itens de lista aninhada (espécies curtas, como acima).
   Só o "##" de seção é numerado pelo código — os sub-títulos dentro do
   corpo, em qualquer nível, ficam como você escrever, sem numeração.

   CAIXA DE FERRAMENTAS — escolha a forma que melhor revela a estrutura
   de cada trecho:
   - Parágrafos curtos, um por ideia, seguindo as viradas do raciocínio —
     nunca um bloco denso de texto.
   - Lista com marcadores pra itens paralelos (princípios, espécies,
     características, hipóteses).
   - Lista numerada pra sequência, etapas, requisitos/condições
     cumulativos, ou quando o professor contou ("são três...").
   - Sublista ANINHADA quando um item se subdivide ("subdivide-se em
     dois", "pode ser X ou Y", espécies de um gênero): os subitens vão
     recuados dentro daquele item (4 espaços por nível), nunca como itens
     irmãos no nível da lista de fora — pôr a espécie no mesmo nível do
     gênero apaga a hierarquia e confunde. Ex.: "Princípio da
     nacionalidade" com "Nacionalidade ativa"/"Nacionalidade passiva"
     recuados dentro dele, e "Princípio da competência universal" de volta
     no nível de fora.
   - Tabela Markdown só quando ela deixa a comparação mais rápida de
     entender do que uma lista — cada célula com as palavras do professor.
     Os dois formatos que funcionam:
     (i) ENUMERAÇÃO com os mesmos atributos por item: cada linha é um item
         que o professor percorreu (as alíneas de um inciso, as partes de
         uma alínea, as variações de um exemplo) e cada coluna é um
         atributo que ele deu pra TODOS eles (hipótese, princípio que
         rege; "o país X pode julgar?", "o Brasil pode julgar?");
     (ii) CONTRASTE ponto a ponto: duas ou três coisas que o professor
         contrapôs em vários pontos concretos (direito penal × processo
         penal; o que acontece na incondicionada × na condicionada quando
         o agente foi absolvido / condenado / cumpriu a pena).
     Antes de manter uma tabela, teste LINHA POR LINHA (e coluna por
     coluna); se falhar, tire a linha — e se sobrarem só uma ou duas
     linhas, troque a tabela por lista ou frase:
     - A linha DIFERENCIA os itens? Se o valor é igual em todas as colunas
       (ex.: "onde ocorreu o crime: fora do território" nas duas
       espécies), é característica comum — vai numa frase antes da
       tabela, ou sai se o texto já disse.
     - A linha se aplica a TODOS os itens? Se só um lado tem conteúdo e o
       outro fica "—" porque o critério não existe pra ele (ex.:
       "condições aplicáveis" numa comparação incondicionada ×
       condicionada), não é critério de comparação — vai como texto/lista
       dentro do item a que pertence. (Célula vazia só vale quando o
       próprio professor deixou aquele ponto sem resposta pra um dos
       lados.)
     - A linha diz algo que outra linha, o título ou o parágrafo logo
       acima já disse? Duas linhas quase iguais ("condições" e "condições
       aplicáveis") ou uma linha que só repete o título são ruído — junte
       ou tire.
     - A coluna/linha foi um critério que o professor usou, ou você criou
       pra preencher a grade? Não invente eixo de comparação.
     Contraste simples entre duas coisas numa única diferença
     ("incondicionada: o Brasil não se submete a nenhuma condição;
     condicionada: se submete a algumas") fica melhor como lista de dois
     itens do que como tabela.
   - LEI EM DESTAQUE (ver "DISPOSITIVOS LEGAIS" acima): o dispositivo
     estudado ancora a organização. Quando uma seção ou sub-título trata
     de um dispositivo, a referência completa vai NO TÍTULO (ex.: "###
     Art. 7º, I, alínea "a", CP — vida ou liberdade do Presidente da
     República"; ou "### Alínea a) — ..." quando o título da seção acima
     já traz "Art. 7º, I, CP"). Cada dispositivo recebe um bloco "Lei:"
     (rótulo abaixo) com a referência completa em negrito e, se o professor leu ou o
     material traz o texto, esse texto entre aspas; em seguida vem a
     explicação do professor sobre ele. Toda menção a dispositivo no meio
     do texto fica em negrito e na forma completa.
   - Negrito nos termos técnicos que ancoram cada ideia e nas frases que o
     professor enfatizou; use negrito nos mesmos pontos que os sinais
     calculados em código (repetição/ritmo, ver acima) já usaram pra
     marcar um bloco como `destaque-prova` — não redetecte isso do zero,
     reaproveite a mesma leitura pra manter o guia consistente com a aula
     editada sobre o que é central.
   - Rótulos visuais (abaixo) pra separar lei, definição, exemplo,
     atenção e pergunta de aluno da explicação corrida.

   RÓTULOS VISUAIS: o app desenha cada parágrafo que COMEÇA com um destes
   rótulos como um bloco colorido próprio (a explicação corrida, sem
   rótulo, fica sem caixa):
   - "Definição:" — quando o professor diz o que algo É ("X é...",
     "chama-se X...", "entende-se por X..."). Um parágrafo próprio por
     definição, com o termo definido em negrito, nas palavras do
     professor: "Definição: **Detração** é o desconto, na pena a cumprir no
     Brasil, do tempo...". Não use pra explicação, consequência ou
     comentário sobre o termo — isso vem logo depois, em parágrafo normal.
     Exceção: numa lista de itens paralelos em que cada item é "termo — o
     que ele é" (espécies de uma classificação), mantenha a lista com
     "**termo** — definição"; a lista já mostra a estrutura.
   - "Lei:" — o dispositivo legal em análise: `Lei: **art. 7º, I, alínea "a",
     CP** — "contra a vida ou a liberdade do Presidente da República"`
     (texto só se foi lido em aula ou está no material; senão, só a
     referência e o assunto dela nas palavras do professor/material).
   - "Exemplo:" — exemplo ou caso prático do professor.
   - "Atenção:" — erro comum, pegadinha ou autocorreção do professor
     (mesmo critério do tipo de bloco `atencao`).
   - "Pergunta de aluno:" — pergunta de aluno e a resposta do professor
     (ver regra geral acima).
   Não existe rótulo "Material da aula:" — o material entra integrado ao
   texto (ver "MATERIAL DADO EM AULA" acima). O rótulo vai no início do parágrafo, fora de lista, com o parágrafo
   separado dos vizinhos por linha em branco — é assim que o app
   reconhece o bloco. Se o exemplo/definição continua numa lista, termine
   o parágrafo com ":" e ponha a lista logo abaixo: ela entra no mesmo
   bloco. Um parágrafo leva um rótulo só (não "Atenção: Aluno: ..." —
   escolha o que predomina).

   FIDELIDADE CONTINUA ACIMA DE TUDO: reorganizar em título, lista,
   tabela, rótulo ou negrito é só isso — reorganizar. As palavras e os
   termos técnicos continuam sendo os que o professor usou, nunca
   resumidos ou reformulados pra caber no formato, e nada de conteúdo
   some. Isso importa de verdade — é comum o professor avisar que a prova
   cobra exatamente o que foi dito em aula, com os termos que ele usou.

   ANTES DE DEVOLVER, releia o corpo como quem vai estudar por ele:
   (a) tem trecho longo sem título? divida; (b) cada item de lista está no
   nível que corresponde ao lugar dele na classificação? (c) toda
   definição, exemplo, pegadinha e pergunta de aluno está com o seu
   rótulo? (d) tem comparação ou enumeração escondida em prosa que ficaria
   mais clara como lista ou tabela? E o contrário: cada tabela passa no
   teste linha por linha (diferencia, se aplica a todos, não repete, é
   critério do professor)? (e) todo artigo/inciso/alínea/
   parágrafo da fala e do material está no guia, com bloco "Lei:" e no
   título da parte que trata dele — forma completa quando aparece sozinho,
   e sem repetir o dispositivo-pai em cada linha de lista/tabela? (f) algum trecho só
   repete o material da aula ao lado do que o guia já explica? apague; o
   que o material acrescenta está integrado no lugar certo? (g) a árvore
   de conhecimento tem a mesma organização, ordem e nomes dos títulos de
   matéria do corpo, com os dispositivos e o assunto de cada um? (h) tem
   sub-título cujo conteúdo é só uma ou duas frases (espécie curta)?
   troque por lista aninhada dentro do gênero; tem título repetindo a
   definição logo abaixo? encurte pro nome.
   Última seção do corpo, sempre que a aula citar algum dispositivo:
   "## Dispositivos legais da aula" — lista de todos eles na forma
   completa, agrupados por artigo (incisos/alíneas/parágrafos aninhados
   dentro do artigo), cada um com o assunto em poucas palavras e o nome
   da seção do guia onde é tratado.
5. Ao final, se houver, uma lista dos trechos marcados como
   "[trecho incompleto/inaudível na transcrição]".

IMPORTANTE: nunca numere manualmente os itens do sumário nem os títulos
das seções (nem "1.", nem "Seção 2", nem nada equivalente) — a numeração
sempre é calculada em código a partir da posição na lista, nunca por
você. Isso evita sumário e seções saírem com numeração inconsistente
entre si.

Devolva JSON válido no formato do schema abaixo — nada além do JSON."""


def _format_segments(segments: list[TranscriptSegment]) -> str:
    lines = []
    for seg in segments:
        lines.append(f"[{seg.start_s:.1f} -> {seg.end_s:.1f}] {seg.text}")
    return "\n".join(lines)


def build_prompt(lesson: Lesson, segments: list[TranscriptSegment], signals_annotation: dict) -> str:
    schema_json = json.dumps(LessonProcessingOutput.model_json_schema(), ensure_ascii=False, indent=2)
    signals_json = json.dumps(signals_annotation, ensure_ascii=False, indent=2)
    transcript_text = _format_segments(segments)

    material_block = ""
    if lesson.material_aula_texto:
        material_block = f"""
MATERIAL DADO EM AULA (LOUSA ETC) — colado à mão, prioritário, sem timestamp:
{lesson.material_aula_texto}
"""

    return f"""{INSTRUCTIONS}

MATÉRIA: {lesson.subject.nome} ({lesson.subject.sigla})
DIPLOMA PADRÃO: {lesson.subject.diploma_padrao or "não definido"}
AULA: {lesson.titulo} — {lesson.data.isoformat()}

SINAIS CALCULADOS EM CÓDIGO:
{signals_json}
{material_block}
SCHEMA DE SAÍDA:
{schema_json}

TRANSCRIÇÃO (start_s -> end_s: texto):
{transcript_text}
"""


def package_as_markdown(lesson: Lesson, prompt: str) -> str:
    """Pacote pra arrastar como anexo no seu Claude — a única ação em que
    isso vale a pena, porque a transcrição inteira não cola num chat comum."""
    header = f"# Processar aula: {lesson.titulo} ({lesson.data.isoformat()})\n\n"
    return header + prompt
