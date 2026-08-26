# Estudos — sistema de estudo do curso de Direito

## Context

Hoje o material das aulas está espalhado: os áudios ficam no app de gravação do iPad e as anotações no Google Docs, sem ligação entre si e sem organização por matéria.

Mas o problema real não é organização — é **retenção e recuperação**. Ninguém reprova em Civil por ter os áudios desorganizados; reprova por não lembrar dos requisitos da usucapião na hora da prova. Um sistema que só arquiva bem é o piso, e corre o risco concreto de ser abandonado em três semanas por nunca devolver nada além do que você colocou nele.

Então o objetivo não é um arquivo bonito. É um **pipeline** que transforma cada aula gravada em material de estudo ativo — resumo, artigos citados, índice navegável e cartões de revisão — onde seu trabalho é *aprovar*, não *criar*. A transcrição não é produto final de leitura; é matéria-prima. O app existe para você precisar reouvir a aula **menos**, e para chegar na prova tendo respondido perguntas em vez de ter reescutado áudio.

Restrição que define a arquitetura: transcrição de boa qualidade (Whisper `large-v3`) exige GPU, e a GPU está na máquina local (RTX 4070 12GB), não na VPS.

**Estado atual:** pasta vazia, projeto do zero. Disponíveis: Python 3.12.10, Node 24, git, RTX 4070 12GB, VPS Ubuntu 24.04 com Docker, domínio próprio.

---

## O pipeline (o coração do sistema)

```
  upload do iPad (2 toques)
        ↓
  transcrição na sua GPU  (large-v3, ~6 min por aula de 2h)
        ↓
  análise em código: repetições · queda de ritmo (ditado) · tempo por tópico
        ↓
  IA em uma passada:  AULA EDITADA (o material de estudo)
                      resumo · índice com timestamps · artigos citados
                      datas anunciadas · termos definidos · ~15 cards propostos
        ↓
  você desliza: aceita / edita / descarta      ← seu único trabalho, ~3 min
        ↓
  fila de revisão espaçada + busca + cobertura da ementa
```

Dois extras que caem de graça dessa passada:

- **Datas anunciadas** — o professor solta "a prova vai ser dia 12" no minuto 4 e você esquece. A IA extrai e joga na agenda, com link para o trecho do áudio onde foi dito.
- **Índice da aula** — a IA segmenta a aula em tópicos com timestamp. É isso que torna o áudio realmente reutilizável: você pula direto pro trecho em vez de procurar.

---

## A aula editada — o artefato que você realmente estuda

Transcrição bruta de aula é quase ilegível: repetição, digressão, "né", correção no meio da frase, ordem embaralhada. Resumo de 600 palavras é curto demais para estudar de verdade. O que falta no meio é uma **apostila da aula** — o conteúdo reescrito de forma limpa e organizada, com destaque no que o professor sinalizou como importante. É esse o artefato que abre por padrão quando você entra numa aula.

**Três níveis, e nenhum substitui o outro:**

| Artefato | O que é | Para quê |
|---|---|---|
| **Transcrição bruta** | Literal, com timestamp por palavra. Nunca apagada. | Verdade de referência, busca, âncora do áudio |
| **Aula editada** | Reescrita, deduplicada, organizada em seções, com destaques | **Estudar** — é o que você lê |
| **Resumo + cards** | 600 palavras + ~15 perguntas | Revisar rápido e fixar |

**A repetição é as duas coisas ao mesmo tempo.** Este é o ponto central do design: o professor repetir a mesma ideia três vezes é justamente o que torna a transcrição cansativa *e* o sinal mais forte de que aquilo cai na prova. Então deduplicar não é apagar — é **fundir as ocorrências numa passagem só e usar a contagem para elevar o destaque**, guardando todos os timestamps de origem. Uma ideia repetida 3× vira um bloco marcado, não um bloco deletado.

**Sinais de importância, e de onde vêm:**

| Sinal | Como é detectado |
|---|---|
| "isso cai na prova", "anotem", "sublinhem" | IA, no texto |
| **Ditado** — professor desacelera para você copiar | **Código**: queda brusca de palavras/minuto nos timestamps do Whisper |
| **Repetição** ao longo da aula | **Código**: agrupamento por similaridade, contagem de ocorrências |
| **Tempo gasto** no tópico | **Código**: duração do trecho |
| Ato definitório ("chamamos isso de…") | IA — alimenta também o glossário |
| Citação de artigo, "exemplo clássico" | IA |
| Resposta a pergunta de aluno | IA — geralmente esclarece confusão comum, e confusão comum vira prova |

Os três sinais em código são calculados **antes** da chamada de IA e entregues como anotação no prompt. São determinísticos, custam nada, e melhoram muito a qualidade do destaque — a IA não precisa adivinhar o que foi ditado, ela recebe essa informação.

**Formatação é vocabulário fechado, não estilo livre.** A saída estruturada obriga a IA a classificar cada bloco em um conjunto fixo — sem isso, cada aula sai com uma estética diferente e a página vira colcha de retalhos:

| Tipo | Aparência |
|---|---|
| `destaque-prova` | Faixa lateral forte + ícone — o professor disse que cai |
| `ditado` | Bloco citado, fonte levemente diferente — copiar literal |
| `conceito` | Termo em destaque, ligado ao glossário |
| `exemplo` | Recuado, tom mais leve |
| `atencao` | Erro comum, pegadinha, autocorreção do professor |
| `normal` | Corpo do texto |

**A garantia contra a IA inventar ou perder coisa.** Cada bloco carrega `start_s`/`end_s` e tem um botão **▸ ouvir o original**. A transcrição bruta nunca é apagada e continua sendo a fonte da busca. Se um bloco parecer estranho, um toque te leva ao professor dizendo aquilo. Sem essa âncora, uma paráfrase silenciosamente errada viraria matéria de estudo — com ela, o erro é verificável em dois segundos.

**Por que a busca não indexa a aula editada.** A busca continua sobre a **transcrição bruta** (mais docs, comentários e definições). Indexar as duas versões daria dois resultados para a mesma fala e poluiria tudo. Como cada bloco editado guarda seu intervalo de tempo, um acerto na transcrição sabe abrir o bloco correspondente na aula editada — melhor dos dois mundos, sem duplicar índice.

### A fonte continua sendo a transcrição — recortada, não inteira

Paráfrase em texto jurídico é perigosa de um jeito que não é em outras matérias: "poderá" × "deverá" separa faculdade de obrigação, "prescricional" × "decadencial" muda o regime inteiro, "nulo" × "anulável" muda quem pode alegar e quando. Uma IA reescrevendo com fluência tende justamente a suavizar essas diferenças, e o erro fica *invisível* porque o texto continua lendo bem. Por isso **a aula editada não é fonte de verdade para nada** — ela é material de leitura e índice.

Mas mandar as duas horas de transcrição em toda chamada também não serve: encarece, e sobretudo **inviabiliza a ponte manual**, já que 27 mil tokens não se colam num chat.

A saída é que o eixo certo não é *editada × bruta*, é **inteira × recorte**. Quase nenhuma tarefa depois da primeira precisa da aula toda — "mais cards sobre usucapião" precisa dos 12 minutos em que ele falou de usucapião. E a aula editada já tem as seções com intervalo de tempo, ou seja, **ela serve de índice para recortar a transcrição crua**:

> **fonte = transcrição bruta na janela do tópico** (2–5k tokens)
> **+ o sumário das seções da aula editada** como mapa de navegação (algumas centenas de tokens)

Palavras literais do professor, contexto pequeno, ponte manual funcionando, custo parecido com o da aula editada. A aula editada deixa de carregar um peso que não é dela e volta a fazer o que faz bem: ser lida e servir de mapa.

**O processamento inicial continua sendo uma chamada só.** Parece que dividir em duas (organizar primeiro, derivar depois) sairia mais barato, e sai mais caro — você pagaria a aula editada duas vezes, uma como saída e outra como entrada:

| | Entrada | Saída | Total |
|---|---|---|---|
| **Uma chamada** (organiza e deriva junto) | 27k · $0,135 | 12k · $0,30 | **$0,435** |
| Duas chamadas | 27k + 8k · $0,175 | 8k + 4k · $0,30 | $0,475 |

*(Exceção: no modo manual, dividir compensa mesmo custando um pouco mais — a primeira etapa vira o `.md` baixável e, da segunda em diante, é tudo copiar e colar.)*

### A mesma arquitetura vale para os livros

Áudio e imagem seguem exatamente o mesmo desenho, e vale enunciar como princípio único:

| Mídia | Verdade final | Fonte de trabalho | Recorte |
|---|---|---|---|
| Áudio | o áudio | transcrição literal (Whisper) | por intervalo de tempo |
| Imagem | a foto da página | transcrição literal (visão) | por intervalo de páginas ou seção |

Depois de transcrito, **a imagem não volta a ser enviada**: gerar cards, questões, verbetes ou comparar uma explicação sua lê o **texto transcrito** do trecho, não as fotos. Mandar imagens em toda chamada seria caro, lento e inútil — a leitura já foi feita uma vez, com qualidade.

E há uma diferença importante em relação à aula editada: a transcrição por visão é **transcrição, não paráfrase**. Ela não reformula, não resume, não reorganiza — por isso não carrega o risco de distorção que nos fez descartar a aula editada como fonte. O que ela tem é o risco de *erro de leitura*, e contra isso vale a mesma proteção do áudio: a imagem fica guardada e cada trecho tem **▸ ver a página original**.

O recorte também é o mesmo: pedir cards de um capítulo manda as páginas daquele capítulo, não o livro inteiro — e quando o trecho está marcado por matéria (acima), o alvo fica ainda mais preciso.

### E a transcrição também não é a verdade — o áudio é

Vale registrar porque é fácil esquecer: o Whisper erra, e erra pior exatamente onde o Direito é sensível — número de artigo ("1.238" virando "1238" ou "mil duzentos e trinta e oito"), latim ("erga omnes", "dolus bonus", "usucapião"), nomes de doutrinadores. Tratar a transcrição como infalível remove só *uma* das duas camadas de distorção.

Três proteções, sendo a terceira específica para isso:

1. **▸ ouvir o original** em cada bloco — o áudio é a instância final.
2. **Citação literal** guardada junto de cada verbete do glossário, com timestamp.
3. **Sinalização de baixa confiança.** O Whisper devolve probabilidade por palavra. Toda citação de artigo e todo termo em latim abaixo do limiar aparece **marcado na aula editada**, com o áudio a um toque, para você confirmar ou corrigir. É o campo onde o erro é mais provável e mais caro — um card que decora "art. 1.239" quando era 1.238 é pior que não ter card. Confirmar é um toque, e a confirmação fica registrada para não perguntar de novo.

---

**Tela inicial = fila, não arquivo.** O que faz abrir o app todo dia:

> Hoje: **24 cards** para revisar · Prova de **Civil em 9 dias** · 1 aula sem resumo

---

## As matérias deste semestre

| # | Matéria | Sigla | Camada de artigos |
|---|---|---|---|
| 1 | Teoria Geral do Direito Civil | TGDC | **Forte** — Código Civil, parte geral |
| 2 | Ciência Política | CPOL | Fraca — doutrinária |
| 3 | História do Direito | HIST | Fraca — doutrinária |
| 4 | Teoria Geral do Crime | TGC | **Forte** — Código Penal, parte geral |
| 5 | Direitos Humanos | DH | **Forte** — CF/88 e tratados internacionais |

Essas cinco matérias compartilham vocabulário com sentidos divergentes — "culpa", "fato jurídico", "sujeito de direito", "norma" significam coisas diferentes em Civil, Penal e Ciência Política. É por isso que o glossário guarda **todas** as definições lado a lado em vez de eleger uma.

Vale calibrar a expectativa: **TGDC, TGC e Direitos Humanos** alimentam bem a camada de artigos — parte geral do CC e do CP são densas em dispositivo, e DH gira em torno do art. 5º da CF e de tratados. **Ciência Política e História do Direito** quase não citam artigo; nessas duas o valor vem do resumo, dos cards e da busca, e a tela de artigos fica praticamente vazia — o que é esperado, não um defeito.

Um detalhe que a IA precisa saber por matéria: em TGC, "art. 121" sem diploma significa Código Penal; em TGDC, significa Código Civil. Cada matéria carrega um **diploma padrão** (`subject.diploma_padrao`) usado para resolver citações sem prefixo.

---

## Camada jurídica: o artigo como unidade atômica

Nenhum app de estudo genérico sabe disso; o nosso sabe. Uma regex sobre a transcrição e as anotações captura `art. 1.238`, `§ 2º`, `inciso III`, `CF/88`, `Súmula 331`, `CDC`, `CPC`, e normaliza para uma chave canônica (`CC:1238`, `CF:5:LXXVIII`, `SUM-TST:331`).

Isso destrava uma tela que não existe em nenhum outro lugar:

> **Art. 1.238 CC** — citado em 4 aulas
> · Civil I · 12/03 · 47:20 — *"o prazo de 15 anos independe de justo título..."*
> · Civil I · 19/03 · 1:12:05 — comparação com o parágrafo único
> · Suas anotações: 2 trechos · Seus cards: 3

Custa pouco (regex + tabela de códigos) e serve tanto para prova dissertativa quanto para OAB. As citações também viram sugestão automática de tópicos da ementa cobertos pela aula.

---

## Glossário — a definição do *seu* professor

Não é um dicionário jurídico genérico. É **o seu dicionário jurídico**, construído a partir de como os seus professores definiram cada termo — que é o que a prova cobra. "Culpabilidade" tem mais de uma formulação doutrinária, e a que vale é a que foi adotada em aula.

**Ele é do curso inteiro, não da matéria.** Termo jurídico não pertence a uma disciplina: "boa-fé", "sujeito de direito", "norma", "prescrição" atravessam Civil, Penal, Constitucional e Processual. Então o glossário é **um só, permanente, cruzando todas as matérias e todos os semestres** — e um termo definido em TGDC continua marcado quando aparecer numa aula de Penal daqui a dois anos. Ao longo de dez semestres, é o artefato mais duradouro do sistema: as aulas envelhecem, o glossário só acumula.

Como suas 5 matérias são todas *Teoria Geral* / introdutórias, o gargalo deste semestre é vocabulário, não localizar dispositivo — por isso o glossário entra na Entrega C, antes da camada de artigos (v2).

**De onde vêm os verbetes.** A mesma passada de IA já lê a transcrição inteira; ganha um campo a mais: termos que o professor **definiu**, não apenas mencionou. O gatilho é o ato definitório — *"isso a gente chama de…"*, *"define-se X como…"*, *"o conceito de X é…"* —, e junto vem a citação literal e o timestamp. Entram como **propostas**, na mesma tela de aprovação dos cards. Você também pode selecionar qualquer texto no app e criar um verbete na mão.

**Um termo, várias definições — todas visíveis.** O mesmo termo pode ser definido em matérias diferentes, por professores diferentes, e até refinado pelo mesmo professor ao longo do semestre. O card **não escolhe por você**: mostra todas, cada uma com sua procedência, e deixa o julgamento com quem está estudando. Quando as definições divergem, essa divergência é informação — é justamente o tipo de coisa que cai em dissertativa.

O termo fica com sublinhado pontilhado discreto; tocar abre um **card sobreposto, sem sair da página**:

> **Culpa** — 3 definições
>
> **▸ Teoria Geral do Crime** · Prof. ___ · aula de 19/03 *(esta matéria)*
> Elemento normativo do tipo: inobservância do dever objetivo de cuidado, nas modalidades imprudência, negligência e imperícia.
> 🔊 *"...culpa aqui não é sentimento, é quebra de dever de cuidado"* — 42:10 ▸ **tocar**
>
> **▸ Teoria Geral do Direito Civil** · Prof. ___ · aula de 12/03
> Em sentido amplo, abrange dolo e culpa estrita; é pressuposto da responsabilidade subjetiva.
> 🔊 *"...no civil a gente usa culpa em sentido largo, que engloba o dolo"* — 1:03:55 ▸ **tocar**
>
> **▸ Teoria Geral do Crime** · Prof. ___ · aula de 26/03 *(refinamento)*
> Acrescentou a previsibilidade objetiva como requisito autônomo.
> 🔊 *"...eu falei três elementos, na verdade são quatro"* — 08:20 ▸ **tocar**
>
> Artigos: art. 18 CP · art. 186 CC · Seus cards: 2

**Qual definição vem primeiro sai do teor do texto que você está lendo**, não de uma regra fixa: pesa a matéria do documento, a proximidade de vocabulário entre o parágrafo em volta e cada definição, e a recência. Numa aula de Penal falando de dever de cuidado, a de TGC sobe; num trecho de livro sobre responsabilidade civil, a de TGDC. E você pode **fixar** a preferência para uma matéria quando quiser resolver na mão.

O ponto importante é que **errar essa ordem não custa nada** — o card mostra todas de qualquer jeito, e a ordenação é só conveniência. Isso permite usar uma heurística simples sem risco de esconder a definição certa.

Esse botão de tocar é o que fecha o ciclo: você não lê a definição, você **ouve o professor dando ela**.

**Três armadilhas, e como o plano as evita:**

1. **Excesso de link — e ele piora com um glossário universal.** Marcar toda ocorrência de todo termo torna o texto ilegível, e o problema cresce quando o glossário cobre o curso inteiro: palavras genéricas como "norma", "fato" ou "ato" aparecem em todo parágrafo de toda matéria. Três regras: **só a primeira ocorrência por bloco**, sublinhado pontilhado (nunca azul de link), nunca dentro do próprio card; um **interruptor global** na barra; e um **botão por verbete para parar de destacar automaticamente** — o termo continua no glossário, continua pesquisável e continua abrindo quando você procura, só deixa de poluir o texto.
2. **Muitas definições no mesmo card.** O risco espelhado do anterior: um termo com oito definições vira uma parede. Regra: a da matéria atual aberta, as demais recolhidas com uma linha de cabeçalho cada (matéria · professor · data), e ordenação por relevância — matéria atual primeiro, depois as mais recentes. Acima de ~6, o card corta e oferece *"ver todas"* na página do termo.
3. **Flexão do português.** "negócio jurídico" / "negócios jurídicos", "capaz" / "capacidade", "ilícito" / "ilicitude". Nada de stemmer — comportamento imprevisível e difícil de corrigir. Cada termo carrega uma **lista explícita de variantes**, normalizadas sem acento e em minúsculas, casadas em fronteira de palavra. A IA propõe as variantes; corrigir é editar uma linha.

**A estrutura que isso exige:** o **termo** é apenas a entrada lexical — a palavra e suas variantes, uma só por grafia em todo o sistema. As **definições** são muitas, penduradas nele, cada uma amarrada à matéria, à aula, ao minuto e à citação literal. Nada de "definição canônica": não há uma vencedora, há um histórico. Isso também elimina duplicação de termo — "culpa" existe uma vez como palavra, com três definições, em vez de três verbetes concorrentes.

**Onde a marcação acontece:** em tempo de renderização, nunca gravada no texto, e **em todo texto do app** — transcrição, aula editada, suas anotações, capítulo de livro, slide, jurisprudência, de qualquer matéria e qualquer semestre. O texto fica limpo no banco; ao renderizar, um passo percorre apenas os **nós de texto** do HTML já gerado (jamais o interior de tags) e envolve os casamentos. Assim, criar ou editar um verbete reflete imediatamente em todo o conteúdo passado — inclusive nas aulas de semestres anteriores — sem reprocessar nada.

**Isso precisa escalar.** Em dez semestres o glossário chega a centenas ou milhares de termos, cada um com variantes, casando contra páginas inteiras de livro. Varredura ingênua (um `replace` por termo) fica lenta rápido. O índice é montado como **autômato de busca simultânea** (Aho-Corasick) sobre todas as variantes normalizadas, percorrendo o texto **uma vez só** independentemente do tamanho do glossário, mantido em memória e reconstruído quando o glossário muda.

**Aba própria — consultar e corrigir.** O glossário é uma das seções principais do app, não só um popover:

- **Lista de termos** de todo o curso, com busca instantânea, filtro por matéria e semestre (mas **sem filtro por padrão** — o glossário é único) e ordenação (alfabética · mais recentes · mais definições). Cada linha mostra o termo, quantas definições tem e em que matérias aparece — e um termo com definições de três disciplinas diferentes é justamente o mais interessante de abrir.
- **Filtro "pendentes"** — as propostas da IA que você ainda não aprovou, para limpar em lote depois de uma semana de aulas.
- **Página do termo** com todas as definições em ordem cronológica, cada uma com matéria, professor, data, citação literal e áudio.

As correções que mais vão acontecer, e que a aba precisa fazer bem:

| Correção | Efeito |
|---|---|
| **Adicionar variante** ("boa fé objetiva" para o termo "boa-fé objetiva") | Passa a marcar em **todo o conteúdo já existente**, na hora — nada é reprocessado |
| **Corrigir a grafia** do termo | Idem: a marcação é em tempo de renderização, então o conserto é retroativo por construção |
| **Editar a definição** | A IA transcreve bem, mas condensa mal às vezes — editar o texto sem perder a citação literal nem o link do áudio |
| **Fundir dois termos** | A IA propõe "negócio jurídico" numa semana e "negócios jurídicos" noutra. Fundir move todas as definições e variantes para o termo que fica |
| **Separar** | O oposto, quando duas coisas viraram um termo só por engano |
| **Descartar uma definição** | Sem apagar as outras do mesmo termo |

Fundir e adicionar variantes são as duas operações que mais vão ser usadas — a IA propondo termos toda semana gera quase-duplicatas naturalmente, e sem uma tela boa de fusão o glossário apodrece em dois meses.

**No resultado da busca.** As definições entram no índice unificado como mais uma fonte (`source_type = definition`), então herdam ranking, filtros e destaque sem código novo. Mas com um tratamento visual distinto: quando o que você buscou casa com um **termo ou uma de suas variantes**, ele aparece **fixado no topo**, antes dos trechos:

> 🔖 **Culpa** — 3 definições · TGC, TGDC ▸ *ver termo*
> ───────────────
> *Teoria Geral do Crime · 19/03 · 42:10* — "...culpa aqui não é sentimento, é quebra de dever..."
> *Suas anotações · Civil, 12/03* — "culpa em sentido amplo abrange o dolo..."

Quando você busca um termo jurídico, quase sempre quer a definição primeiro e as ocorrências depois. A busca casa também pelas **variantes**, então procurar "negocios juridicos" — sem acento, no plural — acha o termo.

**Dois ganhos de graça:**
- **Cards prontos** — frente: o termo (com a matéria, para não ficar ambíguo); verso: a definição daquele professor. Cada definição pode virar seu próprio card, então "culpa em TGC" e "culpa em TGDC" são dois cards distintos — que é exatamente como a prova cobra. Em 1º período esse é provavelmente o material de revisão de maior retorno que existe, e sai sem trabalho extra.
- **Página do termo** — todas as definições em ordem cronológica, com matéria, professor e áudio de cada uma. Dá pra ver como o conceito evoluiu de março para maio e onde as matérias divergem, que é exatamente o tipo de pergunta que cai em dissertativa.

---

## Assunto — a terceira aplicação do mesmo padrão

O plano já resolveu duas vezes o mesmo problema, do mesmo jeito: **a obra é permanente e o uso é datado**; **o termo é global e a definição é datada**. Falta a terceira: **o assunto é global e a cobertura é datada**.

"Prescrição" aparece em Civil I, volta em Civil III e reaparece em Processual. Se o assunto for um tópico preso a uma matéria, cada semestre reconstrói tudo do zero e nada se une. Sendo global, cada matéria apenas **registra que o cobriu**, naquele semestre, com aquelas aulas.

**Os assuntos emergem das aulas, não de um formulário.** Esta é a parte que faz o resto existir. Exigir a ementa cadastrada à mão significa, na prática, que o agrupamento acima da aula provavelmente nunca vai existir — e sem ele não há escopo de prova, não há plano regressivo, não há navegar por assunto.

Então a IA propõe: é **mais um campo na saída estruturada que já existe** — "que assuntos esta aula cobre" —, sem chamada nova nem custo adicional. Depois de três ou quatro aulas, o app sugere:

> Estas aulas parecem cobrir: **Pessoa Natural · Capacidade · Domicílio** — confirma?

Você aceita num toque e a estrutura nasce sozinha do material que já existe. A ementa oficial continua podendo ser cadastrada, mas passa a **enriquecer** em vez de bloquear.

**Vai errar, e por isso nasce com as mesmas ferramentas do glossário.** Assunto proposto por IA fatia demais ("Capacidade" e "Capacidade de Fato" como dois) ou de menos. Sem **fundir, renomear e separar** desde o começo, em dois meses são 60 assuntos quase-iguais e a página do assunto perde o sentido — exatamente o que a fusão de termos evita no glossário.

### A página do assunto

É a tela onde "unir informações antigas" acontece de verdade. A busca devolve uma lista plana de trechos; esta devolve **o assunto montado**:

> **Usucapião**
> *Coberto em:* TGDC · 2026.1 — e em Civil III · 2027.2
>
> **Aulas** 12/03 (47:20) · 19/03 (continuação)
> **Livro** Pereira, v. I, p. 247–290 ▸ ler
> **Anotações** 2 documentos
> **Termos** usucapião extraordinária · justo título · posse mansa
> **Artigos** art. 1.238 · art. 1.242
> **Cards** 12 · acerto 71% · 3 vencidos
> **Última vez que você estudou:** há 9 dias

Dois semestres depois, é aqui que Civil I e Civil III se encontram — sem você ter feito nada além de aceitar as sugestões.

**E o recorte de contexto passa a atravessar aulas.** Quando o professor continua o assunto na semana seguinte, o assunto aponta para as duas aulas, e pedir "mais cards de usucapião" manda os dois trechos em vez de metade da explicação. Isso deixa de ser feature e vira consequência: com o assunto ligando as aulas, `window.py` só segue os vínculos.

---

## Absorção — as oito features de aprendizagem

Tudo aqui explora um ativo que o sistema já tem (áudio com timestamp, a definição do próprio professor, blocos já classificados por importância) em vez de ser feature genérica de app de estudo.

### 1. Cards de discriminação — pares confundíveis

O que derruba em prova de Direito não é esquecer, é **confundir**: dolo eventual × culpa consciente, prescrição × decadência, nulidade × anulabilidade, capacidade × legitimidade. Card isolado treina reconhecimento, não distinção.

A IA, lendo a aula inteira, detecta pares que o professor contrastou e registra **o eixo da distinção** (o que exatamente separa os dois). Daí saem cards que forçam a escolha:

> *"O agente prevê o resultado e assume o risco de produzi-lo."*
> → **dolo eventual** ou **culpa consciente**?
> *(erra → mostra o eixo: assumir o risco × confiar que não ocorrerá, com o áudio dos dois momentos)*

Os pares também viram uma **tela de comparação** lado a lado, alimentada pelas definições do glossário. É a feature de maior retorno específico para Direito.

### 2. Feynman por voz

Botão de gravar, você explica o conceito em voz alta por ~60 segundos, e o sistema devolve o que faltou — comparando com a definição do **seu** professor:

> Você cobriu: conduta típica · ilicitude
> **Faltou:** potencial consciência da ilicitude — o professor tratou como elemento autônomo ▸ ouvir (19/03, 51:40)
> Você disse "culpa" onde ele usa "culpabilidade" — são coisas distintas nesta matéria

Isso é **produção**, não reconhecimento: a forma mais forte de recuperação que existe. E reaproveita o pipeline inteiro que já está construído — gravar, transcrever, comparar com IA.

**Decisão técnica que isso força:** se dependesse da sua GPU, a feature morreria sempre que você estudasse com o PC desligado. Gravações curtas usam `faster-whisper small` na **CPU da VPS** — 60s saem em poucos segundos, e a precisão importa menos porque a IA compara sentido, não transcreve aula. As aulas longas continuam indo para a GPU.

### 3. Dissertativa avaliada

Prova de Direito é escrita. Treinar só com flashcard é treinar o formato errado. A IA gera uma questão no estilo do professor (a partir da aula ou do tópico da ementa), você escreve, e ela avalia contra a definição *dele*, apontando o que faltou e citando o minuto da aula. Cada questão guarda uma **rubrica** — os pontos que precisavam aparecer —, o que torna a correção consistente e revisável por você.

### 4. Cloze na aula editada

Botão **modo estudo** na aula editada: os trechos-chave dos blocos `ditado` e `conceito` somem e você preenche. Transforma leitura passiva em recuperação ativa sem tela nova, reaproveitando blocos que já estão classificados. A feature mais barata da lista.

### 5. Mapa de taxonomia

Suas cinco matérias são árvores de classificação — fato jurídico → ato jurídico → negócio jurídico; crime → tipicidade / antijuridicidade / culpabilidade. A IA gera um diagrama por aula em **Mermaid** (renderizado nativamente, sem biblioteca externa), com os nós ligados aos verbetes do glossário. Em Teoria Geral, a estrutura *é* a matéria.

### 5b. Rede de conceitos

O mapa de taxonomia acima resolve a estrutura *dentro* de uma aula. Mas Direito mistura matérias entre si — "dever de cuidado" aparece em Penal e em Civil, um assunto atravessa disciplinas — e isso pede uma visão **livre, sem hierarquia forçada**, entre aulas e entre matérias. Diferente do mapa de taxonomia, a rede de conceitos **não usa IA** para montar as conexões: comparar cada termo contra o glossário inteiro seria custo O(n²) sem controle. Em vez disso, é **script determinístico**, recalculado sob demanda a cada request, mesmo espírito de `library/coverage.py` ("recalculado sob demanda, nunca guardado").

Nós = Termos do glossário + Assuntos. Arestas vêm de dois sinais que já existem no banco, sem processamento novo:
- **Coocorrência textual** — `glossary/matcher.py::find_matches` (o mesmo mecanismo que já destaca termo em prosa) rodado sobre `EditedBlock.texto`, agrupado em três escopos: **bloco** (um parágrafo — só Termo↔Termo), **aula** (união dos blocos + `LessonAssunto` da aula — Termo↔Termo, Assunto↔Assunto, Termo↔Assunto) e **matéria** (união de todas as aulas — mesmas três, mais denso).
- **Cards de discriminação** (fase 8b) — pares que o professor comparou explicitamente na fala, extraídos na mesma passada de IA que já gera cards. Aresta de alta precisão, com rótulo (eixo da distinção), custo zero adicional.

Nó com `subject_ids` de mais de uma matéria ganha cor de destaque — o sinal visual de conceito-ponte. Não existe página própria: a rede aparece embutida na tela da matéria (escopo matéria) e na tela da aula (escopo aula, com toggle pro escopo bloco na mesma tela, sem navegar). Visualização com **vis-network** vendorizado (`static/vis-network.min.js`, sem CDN — mesmo padrão do `mermaid.min.js`), física posiciona os nós sozinha. Implementação: `network/cooccurrence.py`.

### 6. Calibração de confiança

Antes de revelar o card, você marca *chutei · acho que sei · tenho certeza*. Depois o painel mostra o que nenhum outro número mostra:

> Nos cards em que você disse **"tenho certeza"**, errou **38%** — quase tudo em Teoria Geral do Crime

Confiança mal calibrada é o que faz o aluno chegar na prova achando que sabia. Custa quase nada: um campo a mais no log de revisão.

### 7. Plano regressivo da prova

> **Civil I — prova em 9 dias**
> 12 de 30 tópicos dados · 8 estudados · 2 sem material nenhum
> 43 cards vencidos no escopo · ritmo necessário: **18/dia**
> Mais fraco em: *negócio jurídico* (62% de acerto), *capacidade* (58%)

Transforma o app de arquivo em treinador — e é o que dá motivo concreto para abrir todo dia. Exige a ementa e as datas de prova cadastradas, que por isso sobem para o v1.

### 8. Destaques em áudio

Fila de clipes de 30s com os momentos marcados como `destaque-prova` e `ditado` das últimas aulas, tocando com a tela bloqueada e controles nos fones. Os clipes são cortados com ffmpeg a partir do mp3 já armazenado, usando os timestamps dos blocos — nada de processamento novo. Você já ouve aula no ônibus; melhor ouvir 15 minutos de destaque do que 2 horas de aula inteira.

### Intercalar sai de graça — não estrague

Misturar matérias na mesma sessão retém melhor que estudar em blocos, e a fila por data de vencimento **já faz isso naturalmente**. O cuidado é não adicionar depois um filtro "hoje só Civil" como padrão. Ele existe, mas como exceção deliberada, não como o caminho fácil.

---

## Arquitetura

Duas peças, **um mesmo repositório**, papel escolhido por variável de ambiente:

```
   iPad (Safari/Atalho)                    Máquina local (RTX 4070)
        │ upload de áudio                        │ ROLE=worker
        ▼                                        │
┌──────────────────────────┐   pega job pendente │
│  VPS  ─ ROLE=server      │◄────────────────────┘
│  FastAPI + SQLite        │   baixa áudio original
│  fonte única da verdade  │
│  Caddy (HTTPS)           │◄──── devolve transcrição + mp3 comprimido
└──────────────────────────┘      (VPS apaga o original)
        ▲
        │ navegador (PC, celular, iPad)
```

**Worker em vez de clone com sincronização.** Você mencionou "um clone na máquina local". Recomendo não duplicar o banco: dois bancos editáveis exigem sincronização bidirecional e resolução de conflitos, de longe a parte mais cara e mais bugada de construir. A VPS é a única fonte da verdade e a máquina local roda o **mesmo código** em modo worker — mesmo repositório, mesmo `docker compose`, só com `ROLE=worker`.

**Quantos workers você quiser.** O desktop (RTX 4070) e o notebook (RTX 3060) rodam o mesmo worker e competem pela mesma fila; o claim atômico do job já garante que dois nunca peguem a mesma aula. Cada worker se identifica com um nome, e a aula registra qual máquina a transcreveu. Na prática: o que estiver ligado trabalha, e ligar os dois em fim de semana de acúmulo processa em paralelo.

**E quando nenhum estiver ligado**, a aula fica com status **aguardando worker** — visível na tela inicial, não escondida. Ao lado, um botão **transcrever na VPS agora**: enfileira o job para a CPU da própria VPS com modelo médio (aula de 2h em ~40–60 min, qualidade um pouco menor em latim e termo técnico). É válvula de emergência, acionada por você, não fallback automático — véspera de prova com o PC quebrado não pode ser um beco sem saída.

**Ciclo de vida do áudio:** o iPad sobe o original → worker baixa, transcreve, gera mp3 32kbps mono (~30MB por aula de 2h) e devolve → VPS guarda transcrição + mp3 e **apaga o original**, que fica arquivado em `archive/` no seu PC. Resultado: ~30MB por aula na VPS em vez de ~120MB, e você ouve qualquer trecho de qualquer lugar.

---

## Stack

| Camada | Escolha | Motivo |
|---|---|---|
| Backend | Python 3.12 + FastAPI + Uvicorn | Mesma linguagem do worker (faster-whisper é Python) |
| Banco | SQLite (WAL) + **FTS5** | Busca full-text nativa, zero servidor extra, backup = copiar 1 arquivo |
| ORM | SQLAlchemy 2.0 + Alembic | Migrations simples |
| Frontend | Jinja2 + HTMX + JS vanilla | Sem build, sem `node_modules` — o que importa no Safari do iPad em Wi-Fi de faculdade |
| Layout | CSS Grid + container queries + PWA | Um código servindo iPad (toque), celular e Windows |
| Transcrição | `faster-whisper` `large-v3`, CUDA float16 | ~5GB VRAM; aula de 2h em ~5-8 min na 4070 |
| IA | Claude API (`claude-opus-5`) | Ver seção *IA* |
| Áudio | ffmpeg | Compressão e normalização |
| Deploy | Docker Compose + Caddy | Você já usa Docker; Caddy resolve HTTPS sozinho |

---

## IA

**Modelo:** `claude-opus-5` — 1M de contexto (uma aula de 2h é ~27k tokens, cabe folgado), forte em texto jurídico longo em português. `claude-sonnet-5` é o botão de economia se o custo incomodar.

**Uma passada por aula, saída estruturada.** Em vez de chamar a API cinco vezes, uma chamada com `output_config.format` (JSON Schema) devolve tudo de uma vez: a **aula editada** em blocos tipados com timestamp, o resumo, o índice, os artigos citados, as datas anunciadas, os **termos definidos pelo professor** (com citação literal, timestamp e variantes de flexão) e os cards propostos. Menos custo, menos latência, menos código — e o schema é o que garante que a formatação use o vocabulário fechado em vez de estilo livre.

Junto vêm os **pares confundíveis** (com o eixo da distinção), o **mapa de taxonomia** em Mermaid e os **assuntos que a aula cobre** — todos saem da mesma leitura, sem chamada extra. É esse último campo que faz a estrutura acima da aula existir sem depender de você digitar a ementa.

**Um prompt, dois caminhos.** Os mesmos arquivos de `ai/prompts/` alimentam a chamada de API e a **ponte manual** (seção acima) — o prompt é montado uma vez e ou vai para a API, ou para a área de transferência, ou para um `.md` baixável. Isso mantém os dois modos idênticos em comportamento e evita manter dois conjuntos de instruções em sincronia.

**O prompt recebe as anotações calculadas em código** — grupos de repetição com contagem, trechos de ritmo lento (ditado) e tempo por tópico — como um bloco de metadados junto da transcrição. A instrução central é: *reescrever sem inventar*, preservando os intervalos de tempo de origem em cada bloco.

**Os slides da aula vão junto.** Quando a aula tem slide anexado, ele entra no contexto do processamento. O professor que diz *"como está aí na tela"* deixa de abrir um buraco no material — o conteúdo já está no sistema, só faltava ser usado.

**Reprocessar nunca apaga o que você fez.** Meses depois o prompt estará melhor e você vai querer reprocessar aulas antigas. Tudo que você tocou é **protegido**: card editado, verbete corrigido, definição ajustada, citação confirmada, observação em bloco. O reprocessamento substitui apenas o que continua sendo geração automática intocada, e mostra antes um resumo do que vai mudar e do que será preservado. Sem essa regra, melhorar o sistema custaria perder o trabalho acumulado — e isso precisa estar decidido desde o começo, porque descobrir depois significa já ter perdido.

**Quando a janela não cabe.** Com assuntos atravessando aulas, um recorte pode estourar o orçamento de contexto. O corte é **decisão declarada, nunca silenciosa**: descarta primeiro os trechos de menor destaque, depois as aulas mais antigas, e **avisa na tela** que houve recorte e o que ficou de fora. Truncar em silêncio geraria questões que ignoram metade do assunto sem ninguém perceber.

**Chamadas curtas, sob demanda — sobre a janela.** Feynman por voz, correção de dissertativa, gerar mais cards: todas recebem o **recorte da transcrição** — intervalo de tempo, no caso da aula, ou intervalo de páginas / seção, no caso de livro (2–5k tokens) — mais o sumário como navegação, nunca a fonte inteira. Para livros, quando o trecho já está marcado por matéria, o recorte usa exatamente esse intervalo. Ficam em ~US$ 0,01–0,02 cada; mesmo estudando pesado, somem dentro do custo das aulas. Registradas em `attempt.custo_usd`.

**Cache no que é relido.** O `cache_control` fica no recorte: numa sessão em que você trabalha o mesmo tópico várias vezes (um Feynman, depois uma dissertativa, depois mais cards), da segunda chamada em diante ele é lido a ~10% do preço, com TTL de 1h. Trocar de tópico troca o recorte e recomeça — o cache ajuda dentro de um assunto, não entre assuntos.

**Prompt caching** entra na segunda etapa — ver *Cache no que é relido*, abaixo. Na primeira chamada não há o que reaproveitar: cada aula é lida uma vez só.

**Custo real.** A aula editada é o item mais caro da saída — ela sozinha é alguns milhares de palavras, e token de saída custa 5× o de entrada. Isso sobe a conta em relação ao que eu estimei antes:

| | Por aula de 2h | Semestre (5 matérias × 15 semanas ≈ 75 aulas) |
|---|---|---|
| `claude-opus-5` | ~US$ 0,45 | ~US$ 34 |
| `claude-sonnet-5` | ~US$ 0,21 | ~US$ 16 |

Entre R$ 85 e R$ 185 no semestre inteiro. Ainda é o item mais barato do projeto — a VPS custa mais — mas já não é troco, e vale medir de verdade nas primeiras aulas (a tabela `ai_call` guarda o custo real de cada chamada). Se apertar, o botão de economia é rodar a aula editada em `sonnet-5` e o resto em `opus-5`.

**Você aprova, a IA não decide sozinha.** Cards e datas entram como *propostas*: tela de aprovação com deslizar para aceitar/descartar, editar antes de aceitar. Nada gerado por IA entra na sua fila de revisão sem você ter visto.

---

## Ponte manual — usar seu Claude em vez da API

Toda ação de IA no app tem dois caminhos: **automático** (chama a API, custa tokens) ou **manual** (o app monta o prompt, você cola no seu Claude e traz a resposta de volta). Não é um botão isolado numa tela — é um componente reaproveitado em todas elas.

**Copiar é só a ida.** Se a resposta ficar no chat, o app não ganha card, verbete nem histórico nenhum. Então cada ação manual tem três peças:

1. **Copiar prompt** — monta um texto autossuficiente: a instrução, o contexto necessário (a definição do professor, a rubrica, o trecho da aula) e o **formato de saída exigido**. O chat não tem acesso ao banco, então tudo que a tarefa precisa vai junto.
2. **Colar resposta** — campo ao lado. O parser é tolerante: procura o último bloco ```json, e se não achar tenta o texto inteiro. Sobra de conversa em volta não atrapalha.
3. **Conferir e aceitar** — cai exatamente na **mesma tela de aprovação** já usada pelos cards e verbetes vindos da API. Zero interface nova: a origem muda, o fluxo de revisão é o mesmo.

**Pacote em arquivo — só para o processamento inicial.** Colar 27 mil tokens de transcrição num chat é ruim em qualquer aparelho. Para essa etapa o botão é **baixar pacote**: gera um `.md` com o prompt e a transcrição e você arrasta como anexo (no iPad cai no app Arquivos e anexa igual). É a única ação que precisa disso — da segunda em diante tudo lê a aula editada, que cabe num copiar e colar comum.

**Onde cada modo faz sentido:**

| Ação | Entrada | Custo API | Modo natural |
|---|---|---|---|
| Processar a aula (editada + resumo + cards + termos + pares + mapa) | transcrição inteira, 27k | ~US$ 0,45 | **Automático** — roda sozinho logo após a transcrição, sem você presente. É aqui que está 95% do custo, e é a única ação em que o `.md` baixável vale a pena |
| Feynman por voz | recorte do tópico, 2–5k | ~US$ 0,02 | Qualquer um |
| Correção de dissertativa | recorte do tópico, 2–5k | ~US$ 0,02 | Qualquer um |
| Gerar mais questões / mais cards de um tópico | recorte do tópico, 2–5k | ~US$ 0,02 | **Manual** — ocasional, e você já está sentado estudando |
| Refazer o mapa de taxonomia | sumário + recortes, ~5k | ~US$ 0,01 | Qualquer um |
| Plano regressivo, calibração, cloze, fila de revisão | — | **zero** | Não usam IA — são cálculo em código |

**A entrada da segunda coluna é o que torna a ponte viável.** Como tudo depois da primeira chamada lê um recorte de 2–5k tokens em vez das duas horas, o texto a colar cabe num chat sem esforço — e o que você cola são as **palavras literais do professor**, não uma paráfrase. Só o processamento inicial é grande, e para ele existe o arquivo.

A regra que emerge: **automático quando roda sem você presente; manual quando você já está no computador estudando.** Nenhum dos dois é padrão fixo — em Configurações cada ação tem `automático · manual · perguntar`.

**Ganho além do dinheiro.** A ponte manual também serve para levar a tarefa a um modelo que o app não integra, ou simplesmente para continuar a conversa: colou a correção da sua dissertativa no chat e quer discutir? Está tudo lá. O app deixa de ser uma caixa fechada.

**O custo do modo manual é seu tempo** — cada ida e volta são ~30 segundos. Para 15 cards depois de uma aula, tranquilo; para corrigir 20 dissertativas numa noite de véspera, cansa. Por isso a escolha é por ação, e trocável a qualquer momento.

---

## Interface — iPad primeiro, celular e Windows em seguida

O iPad é o aparelho principal. O layout é desenhado **para o dedo**; o mouse é um caso a mais, nunca o contrário.

**Regras gerais:** nada depende de `hover` (o que aparece ao passar o mouse no PC precisa existir como botão visível); alvo de toque mínimo de 44×44px; inputs com `font-size: 16px` (abaixo disso o Safari dá zoom ao focar e desconfigura a tela); nada só por drag-and-drop; `env(safe-area-inset-*)` respeitado; modo escuro seguindo o sistema; PWA com ícone na tela de início.

**Três larguras**, por container query — o iPad em pé e deitado são situações diferentes:

- **≥1024px (iPad deitado, PC)** — duas colunas: **aula editada** de um lado, player + suas anotações do outro. Tocar em ▸ num bloco pula o player para aquele ponto.
- **640–1024px (iPad em pé)** — uma coluna com abas `Aula · Transcrição · Anotações · Termos · Cards`, player fixo no topo. A aba `Aula` é a aula editada e abre por padrão.
- **<640px (celular)** — uma coluna, navegação inferior com 5 ícones grandes (`Hoje · Aulas · Termos · Buscar · Subir`), player fixo no rodapé. Uso típico: ouvir no ônibus e revisar cards — essas duas telas otimizadas para uma mão.

A navegação principal em todas as larguras é `Hoje · Aulas · Termos · Buscar · Subir` — o glossário é seção de primeiro nível, não algo escondido dentro da aula.

**Player** (você reouve trechos com frequência, então ele é peça de primeira classe): botões grandes de **−15s / play / +15s**, velocidade 1×–2×, posição salva por aula, e **Media Session API** para controles na tela de bloqueio com o áudio seguindo com a tela apagada. Tocar num parágrafo da transcrição pula pra ali; o trecho em reprodução fica destacado e a rolagem o acompanha, pausando assim que você rola manualmente.

**Windows** ganha atalhos como bônus, nunca como único caminho: `/` foca a busca, `espaço` play/pause, `←/→` pulam 15s, `1–4` avaliam o card na revisão.

---

## Google Docs

O Docs continua sendo onde você escreve — confortável no iPad durante a aula, e você já tem o hábito. **Dois mecanismos com papéis distintos:**

| | Para quê | Como |
|---|---|---|
| **Link** | Ler e **editar** | Abre no app oficial do Google. Melhor editor possível, funciona offline. O app não constrói editor nenhum. |
| **Sync** | **Buscar**, IA, cards | Roda em background, invisível. Sem ele, buscar "usucapião" acha o trecho no áudio e não acha nada nas suas anotações — e a IA resume a aula ignorando justamente o que você achou importante o bastante para escrever. |

O app nunca escreve no Docs. Lê para indexar, e manda você pro Google quando é hora de escrever.

**Botões:** *Abrir no Docs* · *Ver aqui* (embute `/preview` ao lado da transcrição) · *Criar doc desta aula*, que monta um link de cópia de modelo com título e pasta prontos:
`https://docs.google.com/document/d/<MODELO_ID>/copy?title=2026-03-12%20Usucapião&folderId=<PASTA_DA_MATÉRIA>`

*Por que não criar pela API:* uma service account não tem cota de armazenamento no Drive e o Google recusa a criação em conta pessoal (`Service Accounts do not have storage quota`) — só funcionaria em Shared Drive do Workspace. O link de cópia custa um toque e não tem essa fragilidade. Criado o doc, o sync o encontra e vincula sozinho.

**Sync (Service Account):** setup único de ~15 min — projeto no Google Cloud, APIs Drive + Docs, service account, JSON na VPS, e **compartilhar a pasta "Faculdade" com o e-mail da service account**. Seus docs seguem privados, ninguém faz login, nenhum token expira. A cada 10 min: `files.list` pedindo só `id, name, modifiedTime` (uma chamada, resposta minúscula), re-baixa só o que mudou, exporta em `text/html` → Markdown (preserva títulos, negrito, listas) e reindexa.

**Vinculação doc ↔ aula:** por pasta, por data no nome do arquivo, e por proximidade com a data da aula. Sem certeza, o doc aparece numa caixa **"Não vinculados"** para você resolver num clique. Docs que não casam com aula nenhuma (resumos, legislação, jurisprudência) ficam como material da matéria — pesquisáveis igual, só não presos a uma data.

**Um Google Doc é um material.** Não existe entidade separada para ele: entra na mesma tabela dos PDFs, fotos e slides, com `origem = gdoc` e os campos de sincronização. Isso não é só economia de tabela — o doc passa a herdar tudo que foi construído para materiais, e o ganho concreto é **poder servir a mais de uma matéria**. Seu resumo de "prescrição" vale em Civil e em Penal; preso a um `subject_id` único, ele valeria em uma só.

---

## Biblioteca — slides, livros e citação acadêmica

O sistema deixa de ser só "as minhas aulas" e passa a ser **o corpus da matéria**: o slide que o professor mandou, o capítulo de livro, o artigo, a jurisprudência, a prova antiga, o resumo que você mesmo escreveu. Tudo entra pelo mesmo caminho, tudo fica pesquisável junto, e cada resultado diz **de onde veio**.

**Tudo entra com um tipo.** Ao adicionar, você marca o que aquilo é. O vocabulário nasce com `slide · livro · capítulo · artigo · jurisprudência · legislação · prova antiga · resumo · anotação`, e é **uma tabela, não um enum fixo** — acrescentar um tipo novo no meio do semestre é cadastrar uma linha, não migrar o banco. Além do tipo, tags livres para o que não couber.

**Extração, e o problema do escaneado.** PDF com camada de texto (slides, e-books, artigos) é extraído direto. Mas boa parte do que circula em Direito é **escaneado** — capítulo fotocopiado, apostila antiga. O sistema detecta a ausência de camada de texto e trata como imagem, pelo mesmo caminho das fotos, abaixo.

### Fotos de páginas de livro

Fotografar capítulo da biblioteca que você não pode levar é rotina, e é um caso mais difícil que o PDF escaneado: página curva na lombada, sombra da própria mão, perspectiva torta, luz irregular.

**A transcrição é feita por modelo de visão.** `claude-haiku-4-5` lê as fotos por padrão — lida bem com curvatura e sombra, distingue nota de rodapé, citação recuada e tabela, e devolve texto limpo em Markdown. Custa **~US$ 0,01 por página**: um capítulo de 20 páginas sai por US$ 0,20, e ~300 páginas ao longo do semestre ficam em torno de **US$ 3**. Quando uma página sair ruim — letra miúda, tipografia antiga, tabela densa —, um botão **refazer com modelo maior** remanda aquela página específica para Sonnet ou Opus. Escalar página a página, e não o capítulo inteiro, mantém o custo baixo onde não precisa.

**Várias fotos = um material, em ordem** — o mesmo padrão de "vários áudios = uma aula". Você fotografa 14 páginas, marca como um capítulo só e define a sequência; a numeração real da obra sai do deslocamento (`pagina_inicial`), então a foto 1 sabe que é a página 247 do livro.

**A foto original fica guardada.** Assim como cada bloco da aula tem *▸ ouvir o original*, cada trecho vindo de foto tem **▸ ver a página original**. Antes de colar uma citação num trabalho, conferir contra a imagem é a mesma proteção que ouvir o professor antes de confiar num card — e aqui vale mais ainda, porque citação errada em trabalho entregue não tem desfazer.

### Onde a transcrição do livro fica, e como você lê

**Enquanto processa.** Cada página tem status próprio: a tela mostra `14 de 20 transcritas`, e uma página que falha fica marcada sozinha, sem travar o resto — dá para reprocessar só ela.

**No banco.** O texto vive em `material_page.texto`, uma linha por página, em Markdown (preservando itálico, nota de rodapé e citação recuada). Em paralelo entra em `chunk`, para a busca. Esse é o dado de verdade.

**Na tela — a leitura do material.** O capítulo aparece corrido, com marcador discreto de página (`— p. 247 —`), **marcação do glossário aplicada** e cada página com **▸ ver a página original**. Em tela larga, texto de um lado e a foto do outro, rolando juntos — que é como se confere transcrição de verdade. É o equivalente da aula editada, mas para livros; a diferença é que aqui não há paráfrase, é o texto literal.

**Você pode corrigir.** A visão vai errar em algum lugar — um número, um nome, uma palavra em latim. O texto é editável, e a página editada fica marcada com a mesma proteção dos cards: **refazer com modelo maior não sobrescreve** o que você corrigiu.

**Levar o texto para fora: copiar e baixar.** Dois botões, disponíveis no material inteiro, num intervalo de páginas ou na sua seleção:

- **Copiar** — joga o texto puro na área de transferência, para colar no trabalho, no Docs ou num chat na hora.
- **Baixar** — gera `.md` (mantém a estrutura) ou `.txt` (limpo), com a **referência ABNT e o intervalo de páginas no cabeçalho** — assim o arquivo já chega sabendo de onde veio. No iPad cai em Arquivos, e de lá o compartilhamento nativo manda para o Drive ou para onde você quiser.

**Por que não gerar o Doc no Drive automaticamente.** Não é escolha estética, é bloqueio da credencial: a service account **não tem cota de armazenamento** e o Google recusa criação de arquivo em conta pessoal — o mesmo motivo pelo qual *"Criar doc desta aula"* usa link de cópia. Fazer automático exigiria OAuth com a sua conta, publicar o app no Google Cloud e manter um token de renovação vivo. Baixar não passa por nada disso: é o servidor mandando um arquivo para o seu aparelho, sem credencial nenhuma. E, como nada nasce dentro da pasta sincronizada, **não existe risco de a transcrição voltar como material duplicado** — dispensa pasta excluída e marca de ignorar.

### A busca ganha procedência e filtro

Cada resultado exibe a **etiqueta da fonte** e a localização exata, e a barra tem filtros por tipo:

> `Aulas` `Anotações` `Slides` `Livros` `Jurisprudência` `Termos`
> ───────────────
> 📕 **livro** · Pereira, *Instituições de Direito Civil*, v. I, **p. 247**
> "...a capacidade de fato é a aptidão para exercer pessoalmente os atos..."  ▸ abrir na página · **copiar citação**
>
> 🎓 **aula** · TGDC · 12/03 · 42:10
> "...o professor distingue capacidade de direito e capacidade de fato..."  ▸ tocar
>
> 📊 **slide** · TGDC · aula 12/03 · slide 14

Isso atende os dois usos que você descreveu com a mesma tela: **estudar** (filtra aulas e anotações) e **procurar fundamentação para trabalho** (filtra livros e jurisprudência).

### Cadastro da obra — uma foto em vez de um formulário

Toda obra tem uma ficha própria, com os campos que a ABNT exige: autores, organizadores ou coordenadores (comum em doutrina jurídica), tradutor, título, subtítulo, edição, volume, tomo, local, editora, ano, ISBN.

**Preencher tirando foto.** A **ficha catalográfica** — no verso da folha de rosto — traz tudo isso já normalizado pela própria biblioteca, e é fonte mais confiável que a capa. Como o pipeline de visão já existe para as páginas, o mesmo mecanismo lê a ficha e **preenche os campos sozinho**; você só confere e corrige. Cadastrar um livro vira uma foto, não um formulário.

**Imagens da obra.** Cada obra guarda capa, contracapa, folha de rosto e ficha catalográfica. Servem para três coisas: a contracapa costuma trazer o ISBN em código de barras, a ficha é a prova de origem dos dados quando a referência for questionada, e a capa faz a biblioteca virar uma **estante visual** — você reconhece o livro de relance em vez de ler uma lista de títulos.

**Campo de referência manual, sobrepondo o automático.** A ABNT tem casos que geração automática erra: coletânea com organizador, obra traduzida, e-book, volume de série, capítulo dentro de livro de vários autores. Então existe um campo de **referência** livre: preenchido, ele passa a ser o que o botão de copiar entrega, ignorando a montagem automática. Você escreve uma vez e todas as citações daquela obra saem certas.

### Livros atravessam semestres — a obra é permanente, o uso é datado

O mesmo *Direito Civil* pode acompanhar você por seis semestres, entrando aos pedaços: um capítulo em TGDC agora, outro em Civil III daqui a dois anos. Então a obra **não pertence a uma matéria** — ela é um item permanente da sua biblioteca. O que pertence a uma matéria e a um semestre é **o uso** de cada parte.

Na prática: a obra é criada uma vez, e cada porção que você sobe registra onde foi usada. Dois anos depois, o histórico está lá — *capítulos 1–3, TGDC, 2026.1; capítulos 15–16, Civil III, 2027.2* — e a mesma parte pode ser usada em mais de uma matéria sem ser duplicada.

**A ordem se resolve pelas páginas, não à mão.** Cada porção guarda seu intervalo na obra (p. 247–290), e a ordenação sai disso automaticamente: um capítulo adicionado três semestres depois cai no lugar exato sem você posicionar nada, e continua correto para sempre. Ordenação manual existe como recurso para quando as páginas não forem conhecidas — foto de capítulo sem numeração visível, por exemplo.

**O sumário fotografado vira o esqueleto da obra.** Uma foto do sumário e a visão extrai a estrutura completa — títulos de capítulo e páginas de início. A partir daí cada porção encaixa num capítulo e a obra mostra **o que você tem e o que falta**:

```
Instituições de Direito Civil, v. I
▓▓▓▓▓░░░░░▓▓▓░░░░░░░░░▓▓▓▓
Cap. 1–3   ✓ TGDC 2026.1        p. 1–120
Cap. 4–6   — ausente            p. 121–240
Cap. 7–8   ✓ TGDC 2026.1        p. 241–300
Cap. 9–14  — ausente            p. 301–520
Cap. 15–16 ✓ Civil III 2027.2   p. 521–580
```

Em seis semestres, é a diferença entre uma pasta de PDFs soltos e saber exatamente o que já existe daquele livro — inclusive na hora de decidir se vale fotografar de novo na biblioteca.

**Aviso de sobreposição.** Subir uma porção cujo intervalo de páginas invade outra já existente dispara um aviso antes de gravar, com a opção de substituir (a foto nova ficou melhor) ou manter as duas. Sem isso, seis semestres de adições viram capítulos duplicados com transcrições ligeiramente diferentes, e a busca passa a devolver o mesmo trecho duas vezes.

### Marcar trechos por matéria — inclusive anos depois

O vínculo com a matéria **não pode ser no arquivo inteiro**. A Constituição é o caso extremo e o mais claro: um único volume atende Ciência Política nos arts. 1º–4º, Direitos Humanos no art. 5º, Administrativo a partir do 37, Econômico a partir do 170. Manuais grandes se comportam igual — capítulos diferentes caem em provas de disciplinas diferentes, em semestres diferentes.

Então **o uso carrega intervalo**: você seleciona um trecho — por seção do sumário ou por faixa de páginas — e marca a matéria, o semestre e um rótulo. O mesmo material acumula quantos usos você quiser, cada um com seu recorte:

```
Constituição Federal comentada
├ Títulos I–II, arts. 1º–4º    → Ciência Política · 2026.1
├ Art. 5º (caput e incisos)    → Direitos Humanos · 2026.1
├ Arts. 37–43                  → Dir. Administrativo · 2027.1
└ Arts. 170–192                → Dir. Econômico · 2028.2
```

**E é marcável depois, sempre.** Você não precisa adivinhar no upload o que vai ser usado daqui a três anos: em qualquer momento futuro, abre a obra, seleciona o trecho e adiciona um uso novo. Nada é reprocessado, nada é duplicado — só um vínculo a mais.

**É isso que dá escopo à geração de estudo.** Com o recorte marcado, "gerar cards do art. 5º para Direitos Humanos" tem um alvo preciso: não o livro inteiro, não o capítulo inteiro, mas exatamente o trecho daquela matéria. Sem isso, ou você gera material demais, ou gera do lugar errado.

### Citação pronta para o trabalho

O botão **copiar citação** devolve a referência em ABNT já com a página:

> PEREIRA, Caio Mário da Silva. **Instituições de direito civil**: introdução ao direito civil. 33. ed. Rio de Janeiro: Forense, 2024. v. 1, p. 247.

E **página do PDF ≠ página do livro**: um capítulo escaneado que começa na página 247 da obra é a página 1 do arquivo. Cada material guarda esse deslocamento, e tanto a citação quanto o resultado da busca mostram a **página real da obra**. É o detalhe que separa uma citação correta de uma errada no trabalho entregue.

**Uma obra, vários arquivos.** A referência bibliográfica é uma entidade própria: três capítulos digitalizados do mesmo livro apontam para a mesma obra e geram citações consistentes, sem você redigitar os dados.

**Material amarrado a uma aula ou solto na matéria.** O slide daquela aula fica na aula; o manual da disciplina fica como material da matéria, aparecendo na busca sem estar preso a uma data. Ambos alimentam busca, glossário e cards igual à transcrição. O vínculo é sempre pelo **uso** — é ele que carrega matéria, semestre e aula —, o que permite que o mesmo material sirva a mais de um contexto sem cópia.

---

## Modelo de dados

O ponto central: **transcrição, docs e notas viram o mesmo tipo de coisa na hora de buscar e na hora de alimentar a IA** — um `chunk` de texto com procedência.

```
subject        matéria: nome, sigla, professor, cor, semestre, ativa, diploma_padrao,
               continua_de → subject anterior (TGDC → Civil II → Civil III)
               drive_folder_id, doc_modelo_id
               → encerrar semestre arquiva a matéria sem apagar nada; a seguinte
                 herda glossário e cards, que continuam na fila de revisão
assunto        **global**: slug, titulo, descricao — permanente, sem matéria
               → "prescrição" é um só no curso inteiro, de Civil I à OAB
assunto_cobertura  assunto_id, subject_id, semestre, ordem (posição na ementa),
               status(pendente|dado|estudado), origem(ia|ementa|manual)
               → é aqui que mora a datação: a matéria registra que cobriu o assunto
lecture_assunto  N:N — aula ↔ assunto (o que liga duas aulas do mesmo tema)
exam           prova: subject_id, data, escopo (assunto_cobertura), peso
lecture        aula: subject_id, data, título, status, comentario_md
               → pode existir sem áudio (esqueceu de gravar, seminário, aula de slides):
                 recebe anotações e materiais e participa de tudo, menos do que exige áudio
asset          arquivo: lecture_id, kind(original|web), ordem, path, bytes, duration_s
               → uma aula pode ter vários originais (o intervalo parte a gravação);
                 o worker concatena na ordem antes de transcrever
worker         máquina: nome, tipo(gpu|cpu-vps), modelo, last_seen
work           obra bibliográfica: tipo, autores, organizadores, tradutor,
               titulo, subtitulo, edicao, volume, tomo, local, editora, ano,
               isbn, doi, url, referencia_manual (sobrepõe a ABNT automática)
               → uma obra, vários arquivos (3 capítulos digitalizados = 1 referência)
               → a obra é **permanente e sem matéria**: atravessa semestres
work_image     imagem da obra: work_id, tipo(capa|contracapa|folha_rosto|ficha|sumario), path
               → ficha preenche os campos por visão; sumário vira a estrutura; capa é a estante
work_section   estrutura da obra (do sumário): work_id, ordem, nivel, titulo,
               pagina_inicial, pagina_final
material       qualquer fonte que não é áudio: work_id (nulo se avulso), tipo_id, titulo,
               path, mime, pagina_inicial, pagina_final (intervalo na obra → ordena sozinho),
               ordem_manual (só quando as páginas são desconhecidas),
               origem(pdf|foto|texto|link|gdoc), status, indexado_em,
               gdoc_id, modified_time, synced_at, sync_error   (só quando origem=gdoc)
material_use   onde foi usado: material_id, subject_id, semestre, lecture_id (nulo),
               assunto_id (nulo), work_section_id (nulo) | pagina_inicial, pagina_final,
               rotulo, lido_ate (página onde você parou de ler)
               → N:N **com intervalo**: o art. 5º da CF vai para Direitos Humanos e os
                 arts. 37–43 para Administrativo, no mesmo arquivo, em semestres
                 diferentes. Marcável a qualquer momento, sem reprocessar nada
material_page  página: material_id, ordem, pagina_obra, image_path, texto,
               extraido_por(nativo|visao), ai_call_id, status, editado_em
               → `editado_em` preenchido = protegido: "refazer com modelo maior"
                 nunca sobrescreve a página que você corrigiu
               → serve para PDF e para foto; a imagem guardada é o "ver o original"
material_tipo  vocabulário extensível: slug, rótulo, ícone, cor
               seed: slide · livro · capítulo · artigo · jurisprudência ·
                     legislação · prova antiga · resumo · anotação
material_tag   N:N — tags livres além do tipo
block_note     observação sua num bloco da aula editada: block_id, texto_md, created_at
segment        transcrição: lecture_id, idx, start_s, end_s, text, confidence
word_flag      trecho de baixa confiança: lecture_id, start_s, end_s, texto,
               tipo(citacao|latim|nome), prob, status(pendente|confirmado|corrigido),
               texto_corrigido

summary        saída da IA: lecture_id, resumo_md, pontos_md, gerado_em, ai_call_id
section        seção da aula editada: lecture_id, idx, titulo, start_s, end_s
block          bloco de conteúdo: section_id, idx, texto_md, start_s, end_s,
               tipo(destaque_prova|ditado|conceito|exemplo|atencao|normal), repeticoes
outline_item   índice da aula: lecture_id, start_s, título   (IA)
announcement   data anunciada: lecture_id, tipo(prova|entrega), data, trecho, start_s, confirmado

citation       artigo citado: chave canônica (CC:1238), diploma, artigo, §, inciso
citation_ref   N:N — citation ↔ chunk (onde foi citado, em que minuto)

term           entrada lexical: slug (normalizado), rótulo de exibição, destacar (bool)
               → **global**: uma por grafia em todo o curso, sem matéria e sem semestre
                 `destacar = false` mantém no glossário e na busca, sem poluir o texto
term_alias     term_id, alias normalizado (sem acento, minúsculo) — variantes de flexão
definition     term_id, subject_id, lecture_id, material_id, start_s, professor,
               definicao_md, citacao, tipo(definiu|refinou),
               status(proposto|ativo), origem(ia|manual)
               → várias por termo, de matérias e semestres diferentes; sem "canônica"
term_pin       preferência fixada: term_id, subject_id, definition_id
               → resolve na mão qual definição abre primeiro numa dada matéria
term_citation  N:N — term ↔ citation (o termo e os artigos que o disciplinam)

               → **Google Doc é um material** com `origem = gdoc`: ganha `gdoc_id`,
                 `modified_time`, `synced_at`, `sync_error`, e usa `material_use`
                 como qualquer outra fonte — logo pode servir a várias matérias

ai_call        toda chamada de IA: tipo(processar_aula|visao_pagina|feynman|
               dissertativa|cards_extra|mapa|ficha|sumario),
               alvo_tipo, alvo_id, modelo, tokens_in, tokens_out, cache_read,
               custo_usd, via(api|manual), erro, created_at
               → fonte única de custo; retentativa e "refazer com modelo maior"
                 viram linhas novas, não sobrescrevem. É o que torna possível
                 o painel de gasto e o teto mensal

chunk          índice unificado:
               source_type(transcript|material|definition|block_note) · source_id
               source_version (hash do texto de origem — ver *Integridade*)
               lecture_id · material_id · assunto_id
               anchor — segundos no áudio · cabeçalho da seção · **página da obra**
               heading_path · text
               → **sem `subject_id`**: para transcrição a matéria vem da aula; para
                 material ela se resolve por `material_use`, casando a página do
                 anchor contra os intervalos. Um mesmo livro serve quatro matérias
                 em faixas diferentes — matéria não é atributo do trecho
chunk_fts      FTS5 sobre chunk.text (unicode61, remove_diacritics 2)

job            fila: kind(transcribe|summarize|gdocs_sync|backup), lecture_id,
               alvo(gpu|cpu-vps), worker_id, idempotency_key,
               status(...|bloqueado_por_teto), attempts, error
               → `idempotency_key` impede que reenvio do resultado grave duas vezes
card           flashcard: tipo(basico|discriminacao|cloze|termo), front, back,
               source_chunk_id, pair_id, block_id, origem(ia|manual), deriv_key,
               status(proposto|ativo|orfao), editado_em, due_at, interval_d,
               ease, reps, lapses
               → `deriv_key` dá identidade estável ao artefato gerado; `editado_em`
                 preenchido = protegido. Ver *Integridade*. Vale igual para
                 `definition`, `block`, `pair`, `question`, `outline_item`,
                 `announcement` — todo artefato derivado tem `deriv_key`
review         log: card_id, reviewed_at, grade, confianca(chutei|acho|certeza)

pair           par confundível: definition_a_id, definition_b_id, eixo_md, origem
               → nasce de definições (globais), não de matéria — "dolo eventual ×
                 culpa consciente" vale em qualquer disciplina que os discuta
question       dissertativa: assunto_id, lecture_id (nulo), enunciado, rubrica_md, origem
               → presa ao **assunto**, que é global: a questão reaparece numa
                 disciplina posterior e na preparação para a OAB
attempt        resposta livre: tipo(voz|texto), question_id | term_id, texto,
               audio_path, transcrito_em, nota, feedback_md, ai_call_id
setting        chave/valor — inclui o modo por ação (automatico|manual|perguntar)
diagram        mapa: lecture_id, titulo, mermaid, gerado_em
clip           destaque em áudio: lecture_id, block_id, start_s, end_s, titulo, path
device         sessões/convites
```

Busca com **bm25** sobre `chunk_fts`, `remove_diacritics 2` para "usucapiao" achar "usucapião". Cada resultado sabe voltar à origem: chunk de áudio → pula pro minuto no player; chunk de definição → abre a página do termo; chunk de material → abre na origem certa conforme `origem` (PDF na página exata com **copiar citação**, ou o Google Doc no editor). Um casamento com `term_alias` fixa o termo no topo dos resultados, e os filtros por tipo de fonte ficam na barra.

`card.source_chunk_id` é o que amarra tudo: errou o card, ouve os 30 segundos em que o professor explicou.

---

## Integridade — as regras que impedem o banco de apodrecer

Três invariantes que precisam existir **antes da fase 6**, a primeira que gera artefatos de IA. Depois dela, cada uma custa migração e reprocessamento.

### 1. Chave de derivação — o que impede o reprocessamento de duplicar

A regra "reprocessar preserva o que você editou" não se sustenta sozinha: sem uma identidade estável, o sistema não tem como saber que o card novo **é o mesmo** card antigo. Só restariam dois comportamentos, ambos ruins — apagar tudo (perde suas edições) ou inserir tudo (duplica).

*Sem isso:* você reprocessa uma aula que tinha 12 cards, 3 editados por você, e chegam 15 novos. A fila passa a ter 27 cards quase idênticos, com agendamentos independentes, e você revisa a mesma pergunta duas vezes por semana até desistir da fila.

Todo artefato derivado (`card`, `definition`, `block`, `pair`, `question`, `outline_item`, `announcement`) carrega **`deriv_key`** — tipo + intervalo de origem + hash normalizado do conteúdo-fonte. Reprocessar é um *diff* por essa chave:

| Situação | Ação |
|---|---|
| Mesma chave, não editado | Substitui |
| Mesma chave, `editado_em` preenchido | **Preserva** e sinaliza "há versão nova, quer ver?" |
| Chave nova | Insere como proposta |
| Chave sumiu | Marca órfão — **nunca apaga** |

### 2. Ciclo de vida do chunk — o índice é derivado e precisa morrer

Quase tudo no sistema é editável: página de OCR corrigida, definição ajustada, aula reprocessada, Doc ressincronizado, termos fundidos. O plano descrevia como os chunks nascem e nada sobre como morrem.

*Sem isso:* a visão lê "art. 1.239" onde era 1.238, você corrige na tela de leitura, e o chunk antigo continua no índice. Duas semanas depois você busca, acha o trecho, clica em **copiar citação** e cola no trabalho o número errado — com a referência ABNT impecável em volta. O erro que todo o resto do plano se esforça para evitar entra pela porta dos fundos.

Regra: **reindexar é apagar todos os chunks daquela fonte e regravar**, nunca atualizar em cima. Cada chunk guarda `source_version` (hash do texto de origem), e um teste verifica que nenhum chunk aponta para uma versão que não existe mais.

### 3. Matéria não é atributo do trecho

Já refletido no modelo acima: `chunk` não tem `subject_id`. Para transcrição a matéria vem da aula; para material ela se resolve por `material_use`, casando a página contra os intervalos.

*Sem isso:* você marca arts. 1º–4º da Constituição como Ciência Política e o art. 5º como Direitos Humanos, no mesmo arquivo. O chunk da página do art. 5º teria que escolher um `subject_id` — e as duas escolhas erram: com o da primeira marcação, filtrar por Direitos Humanos **não acha o art. 5º**; com nulo, filtrar por Ciência Política **traz o livro inteiro**.

---

## Limites operacionais

Seis regras que não mudam o modelo, mas cuja ausência produz perda de dado ou falha silenciosa.

**Escrita concorrente no SQLite.** WAL aceita muitos leitores e **um escritor**, e há seis fontes de escrita (web, sync do Drive, resultado de worker, visão, backup, reindexação). Dois workers terminando no mesmo minuto: o primeiro insere ~1.500 segmentos e ~300 chunks numa transação; o segundo leva `SQLITE_BUSY`, esgota as tentativas e perde 6 minutos de GPU. Portanto: `busy_timeout` de 30s, escrita de resultado **fatiada** em transações de alguns milhares de linhas, e ingestão de resultado serializada por um escritor único.

**Idempotência no resultado do worker.** O worker envia 8 MB, o servidor grava, a resposta se perde na volta. O worker reenvia e a aula fica com a transcrição em dobro. Cada resultado carrega **chave de idempotência por job**; o segundo commit é recusado com "já recebido".

**Restauração exige modo manutenção.** Trocar o arquivo SQLite embaixo de uma conexão viva, com WAL e shared memory ativos, corrompe: a conexão antiga faz checkpoint do WAL velho por cima do banco restaurado e você fica com um híbrido — pior que qualquer um dos dois, e percebido semanas depois. Restaurar **fecha o pool de conexões**, restaura, reabre.

**Truncamento da janela é decisão, não acidente.** Com assuntos atravessando aulas, "prescrição" pode cobrir cinco aulas e estourar o orçamento de contexto. Cortar em silêncio gera questões que ignoram metade do assunto sem ninguém saber. Então: limite explícito, critério declarado de descarte (trechos com menos destaque primeiro, aulas mais antigas depois) e **aviso na tela** de que houve recorte e do que ficou de fora.

**O teto de custo precisa bloquear, não relatar.** `ai_call` registra depois da chamada; teto exige verificação **antes**. Sem isso, você sobe 20 aulas acumuladas, o sistema passa dos US$ 10 e continua, porque nada consultou o limite. Verificação pré-chamada, estado `bloqueado_por_teto` no job e botão de liberar.

**Clientes de IA, visão e ASR atrás de interfaces.** Não é purismo: os testes que mais importam — preservação de edições no reprocessamento, ciclo de vida do chunk, recorte de contexto — não têm como rodar se cada um exigir chamada real, dinheiro e seis minutos de espera. Interfaces injetáveis com **fixtures gravadas de uma aula real** desde a fase 1.

**Uma nota explícita, não implícita:** a transcrição por visão **envia conteúdo de livro protegido por direito autoral para a API**. É uso pessoal e é sua decisão; fica registrado para que seja escolha, não descoberta.

---

## Acesso

**Domínio:** `drwyver.mecadosjogos.app.br` — temporário, mas já é sobre ele que o Caddyfile e o `.env` são construídos. Trocar depois é uma linha no `Caddyfile` e uma no `.env`; nenhum link fica gravado no banco (as URLs são geradas a partir da configuração, não persistidas).

**Suas máquinas:** você abre uma vez `https://drwyver.mecadosjogos.app.br/?k=<TOKEN>`. O servidor troca a chave por um cookie de sessão e **redireciona removendo o `?k=` da URL** (para não vazar no histórico nem em `Referer`). Sem tela de login, sem senha, válido por 1 ano. O primeiro dispositivo vira `admin`.

**Convite (adiado para depois do v1).** Você perguntou se dá pra colocar o token no aparelho de outra pessoa de modo nativo — **dá, via cookie HttpOnly**, e ela não digita nem copia nada: aparelho sem cookie cai numa página *"Pedir acesso"*, digita um nickname, o servidor grava um cookie `pending_id` e mostra um código de 4 dígitos; você confere o código com a pessoa e aprova no painel escolhendo validade e papel; no próximo poll o servidor **converte o `pending_id` em sessão ativa e grava o cookie definitivo**. É esse último passo que responde sua pergunta.

Foi over-engineering meu colocar isso antes de o app fazer algo útil — são cookies, códigos, painel e polling construídos antes do primeiro resumo existir. Token único cobre seus aparelhos hoje; o convite entra quando um colega pedir. **Proteções desde o v1:** rate limit por IP, `robots.txt` bloqueando tudo, limite de tamanho de upload, nada servido sem sessão válida.

> **Status: feito, com desenho mais simples que o esboçado acima.** Em vez do fluxo pending_id/código de 4 dígitos, virou login de verdade: `/registrar` cria um `User` com `status="pendente"`; `/login` autentica usuário+senha (bcrypt) e só libera sessão pra `status="aprovado"` dentro do prazo (`expira_em`, nulo = permanente — mesmo idioma de `Subject.encerrada_em`); um admin único (semeado na migração 0019, `admin`/`admin` — trocar a senha é o primeiro passo depois do deploy) aprova/recusa/revoga/concede prazo em `/admin/seguranca`. `ACCESS_TOKEN` não autentica mais navegador — ficou só como credencial de máquina (worker de transcrição, Atalho do iOS), que continuam intocados. Rate limit por IP citado acima **nunca foi implementado** (nem no v1 nem agora) — vale registrar como lacuna real, não como proteção que existe.

---

## Estrutura de pastas

```
Estudos/
  server/app/       main.py · db.py · models.py · auth.py · search.py · chunker.py
                    ai/ (client.py · schemas.py · prompts/ · pipeline.py · signals.py
                         bridge.py · parse.py)      ponte manual: montar e ler de volta
                    legal/ (citations.py · codes.py)
                    glossary/ (index.py · matcher.py · render.py · merge.py)
                    library/ (ingest.py · pdf.py · vision.py · abnt.py
                              gdocs.py · html_to_md.py · matcher.py)
                              → Docs entram pela mesma ingestão dos demais materiais
                    routes/ · templates/ · static/
                    study/ (pairs.py · cloze.py · dissertativa.py · feynman.py · plan.py)
                    context/ (window.py)          recorte da transcrição por tópico
                    media/ (clips.py · shortasr.py)      short ASR na CPU da VPS
  worker/           main.py · transcribe.py · compress.py · config.py
  shared/schemas.py     contratos Pydantic entre server e worker
  data/             estudos.db · media/original/ · media/web/     (só na VPS)
  archive/          áudios originais                              (só local)
  docker-compose.yml · docker-compose.worker.yml · Caddyfile · .env.example
```

---

## Fases

O escopo é o que você escolheu — nada foi cortado. O que mudou foi a **ordem**, por duas razões: a ordem anterior tinha dependências quebradas (o glossário marcava livros que só existiam sete fases depois), e um bloco único de catorze fases contradiz o próprio risco declarado no começo deste plano — o app ficar bom só depois da prova.

São **quatro entregas, cada uma utilizável sozinha**. Você usa a A enquanto a B é construída.

| | Entrega | O que passa a ser possível |
|---|---|---|
| **A** | Capturar | Nenhuma aula se perde; tudo transcrito, ouvível e buscável |
| **B** | Estudar | O ciclo fecha: aula vira material de estudo e cards revisados |
| **C** | Corpus | Livros, slides e anotações entram; glossário marca tudo; busca unificada |
| **D** | Treinar | Produção falada e escrita, mapa, destaques e plano da prova |

---

### Entrega A — Capturar

*Fim da entrega: você grava, sobe, e nunca mais perde uma aula. Tudo transcrito e pesquisável por texto.*

**0. Fundação do repositório** — `git init`, estrutura de pastas, `.gitignore`, `.env.example`, `docker-compose.yml`, `Caddyfile` com `drwyver.mecadosjogos.app.br`. **Copiar este plano para `PLANO.md` na raiz do projeto** e criar um `CLAUDE.md` curto apontando para ele — assim qualquer sessão futura encontra o plano sem precisar do caminho, e ele fica versionado junto com o código. Seed das 5 matérias do semestre.

**1. Base, backup e restauração** — FastAPI + SQLite + Alembic + auth por cookie.

**As regras de integridade nascem aqui, não depois.** `busy_timeout` de 30s e escrita fatiada; **clientes de IA, visão e ASR atrás de interfaces injetáveis**, com fixtures gravadas — sem isso os testes que mais importam não rodam; e o **modo manutenção** que fecha o pool de conexões antes de restaurar (trocar o arquivo SQLite sob conexão viva corrompe o banco). Ver a seção *Integridade e limites operacionais*.

Sistema visual: tema claro/escuro, escala de espaçamento, tipografia fluida, componentes com alvo de toque de 44px, esqueleto dos três layouts, manifest de PWA.

**Backup desde o primeiro dia.** Dump diário do SQLite, versionado com retenção, **puxado automaticamente pelo worker sempre que ele conecta** — ou seja, toda vez que você liga o PC, a cópia mais recente vem junto sem você pedir. O banco guarda o semestre inteiro de transcrição, glossário, cards e progresso.

**Só o banco, não a mídia.** Os mp3 comprimidos ficam de fora e o backup fica em poucos megabytes em vez de gigabytes, porque eles são **reconstruíveis**: com os originais arquivados no seu PC e o banco restaurado, o worker regenera os comprimidos e reenvia. Existe uma ação **reconstruir mídia** para isso.

**Botão de restaurar, na VPS.** É a única operação do sistema que apaga dados de propósito, então a tela é desenhada em torno disso:

- **Duas origens** — escolher um backup da própria VPS (caso pequeno: você quer voltar dois dias) ou **enviar um arquivo do seu PC** (o caso real de desastre: a VPS morreu e foi recriada, não há nada local).
- **Comparação antes de confirmar** — mostra lado a lado o que está no ar e o que vai entrar: data, número de aulas, cards e verbetes. Restaurar um backup de duas semanas atrás por engano é o erro provável, e ele precisa ser visível antes de acontecer.
- **Cópia de segurança automática do estado atual** antes de sobrescrever, com o caminho dela na tela — restaurar errado tem volta.
- **Migração de schema na restauração** (Alembic), e recusa explícita se o backup for de uma versão *mais nova* que a aplicação.
- **Bloqueio se houver job em andamento**, para não restaurar por cima de uma transcrição chegando.

**2. Matérias e aulas** — CRUD, lista por matéria, linha do tempo, com as 5 matérias já cadastradas pelo seed (sigla, cor, diploma padrão). **Encadeamento entre semestres**: encerrar uma matéria arquiva sem apagar, e a matéria seguinte (`continua_de`) herda glossário e cards, que seguem na fila de revisão — Direito é cumulativo e cada semestre não pode ser uma ilha. **Mover aula entre matérias**, com cards e definições acompanhando — upload na matéria errada é erro banal, e a procedência das definições precisa seguir correta. **Aula pode existir sem áudio** — seminário, aula de slides, ou o dia em que você esqueceu de gravar. Campo de link do Google Doc com botão *Abrir no Docs* (o restante da integração vem na Entrega C).

**3. Upload do iPad**
Página `/upload` grande e simples; `.m4a/.mp3/.wav`; upload em chunks com retomada automática (aulas de 2h são grandes e o Wi-Fi da faculdade cai). **Seleção de vários arquivos de uma vez**, com matéria por arquivo e a opção de **marcar dois ou mais como uma aula única**, definindo a ordem — o intervalo parte a gravação em dois e isso precisa ser explícito no momento em que você ainda lembra qual é qual. **Atalho do iOS** que recebe o áudio pelo botão Compartilhar do app de gravação. Deploy na VPS com Caddy + HTTPS.

**4. Workers e transcrição** — `GET /api/jobs/next` com claim atômico, `POST /api/jobs/{id}/result` **com chave de idempotência** (reenvio após timeout não pode gravar a transcrição em dobro), heartbeat e retry. **Vários workers** (desktop RTX 4070, notebook RTX 3060) competindo pela mesma fila, cada um identificado por nome; a aula registra qual máquina a transcreveu. Worker: baixa → concatena os originais na ordem → `large-v3` float16 com `word_timestamps` → mp3 32kbps → envia → arquiva. Status **aguardando worker** visível na tela inicial e botão **transcrever na VPS agora** (CPU, modelo médio) como válvula de emergência. Console com progresso e ETA, `--watch` para rodar contínuo.

**5. Leitura e busca simples** — página da aula com **transcrição legível e player sincronizado** (tocar num parágrafo pula o áudio, trecho atual destacado, rolagem acompanhando), −15s/+15s, velocidade, posição salva e Media Session. Busca FTS5 sobre a transcrição, com destaque do trecho e clique levando ao minuto. É pouca coisa depois da fase 4 e **fecha a entrega A com valor real**: mesmo sem nenhuma IA, você já não perde aula e já acha qualquer coisa que o professor falou.

**5b. Revisão humana da transcrição** — adicionada depois, durante a fase 8, mas vive nesta mesma página porque é onde a leitura já acontecia. Motivo de existir: numa aula de ~2h o Whisper erra, e todo o resto (guia, aula editada, cards) herda o erro se ninguém corrigir antes. `transcript_confidence.py` calcula, a partir da probabilidade por palavra que o Whisper já devolve (fase 4, `words_json`), **quais trechos merecem atenção** — e soma um segundo sinal, **repetição de texto idêntico numa janela curta**, porque um Whisper preso num loop de alucinação fica "confiante" reforçando o próprio erro (confirmado com um caso real: seis trechos repetidos com probabilidade individual ~0,8, que a probabilidade sozinha nunca pegaria). Botão **⏭ próximo de baixa confiança** pula direto pros trechos flagados; clique simples toca normal, duplo clique abre edição inline **e** toca aquele trecho em loop — só que o loop vai até o **início do próximo trecho**, não o fim do atual, porque o Whisper deixa buracos entre segmentos (às vezes é pausa real, às vezes é fala que ele simplesmente engoliu) e parar no fim do trecho escondia exatamente onde o conteúdo pode ter sumido. `Transcript.aprovado_em` fecha o ciclo: uma vez aprovada, a transcrição **trava** para edição e para retranscrição — só "reabrir revisão" libera as duas de novo, de propósito, pra uma retranscrição acidental nunca apagar revisão manual silenciosamente. **A fase 6 (etapa 1) só processa aula com transcrição aprovada** — ver "Ponte manual" mais abaixo.

Achado real que motivou boa parte disso: uma frase inteira de ~4s sumiu completamente de uma transcrição de ~111min, sem aparecer em nenhum segmento nem antes nem depois. Extrair o mesmo trecho isolado e rodar o Whisper de novo (sem o contexto acumulado da transcrição longa) reproduziu a frase perfeitamente — confirmando que o problema é `condition_on_previous_text=True` (o padrão do faster-whisper) deixando erro compor erro ao longo de uma transcrição longa e contínua. `shared/transcriber.py` já roda com `condition_on_previous_text=False` por causa disso — ver "Decisões fechadas".

---

### Entrega B — Estudar

*Fim da entrega: o ciclo fecha. A aula vira apostila, cards e fila de revisão.*

**6. IA, aula editada e ponte manual** — antes de qualquer geração: **`deriv_key` em todo artefato derivado**, o *diff* de reprocessamento (substitui · preserva editado · insere novo · marca órfão), a **reindexação por apagar-e-regravar** com `source_version`, e a **verificação de teto antes da chamada** (com estado `bloqueado_por_teto`). São as regras da seção *Integridade* — depois desta fase, cada uma custa migração.

`context/window.py` recorta a transcrição por intervalo de tempo a partir das seções da aula editada, e é ele que monta o contexto de **toda** chamada posterior à primeira. `bridge.py` monta qualquer prompt do sistema para os três destinos (API · área de transferência · `.md` baixável), `parse.py` lê a resposta colada de volta com tolerância a texto em volta, e o resultado cai na mesma tela de aprovação. Configuração de modo por ação (`automático · manual · perguntar`). Marcação de **baixa confiança** em citações de artigo e termos em latim, com confirmação de um toque e o áudio ao lado. **Observação por bloco** — campo para você corrigir ou complementar o que a IA organizou, sem precisar sair para o Docs; suas observações entram na busca. Junto disso: `signals.py` calcula em código os sinais determinísticos (grupos de repetição com contagem, queda de ritmo indicando ditado, tempo por tópico); a passada estruturada descrita acima, com prompt caching, devolve a **aula editada em blocos tipados** mais resumo, índice, artigos, datas, termos e cards. Renderização dos seis tipos de bloco com estilos distintos e botão **▸ ouvir o original** em cada um. Tela de **aprovação** (deslizar aceita/descarta/edita) para cards, termos e datas. A página da aula passa a abrir na **aula editada**, com transcrição, anotações e cards como abas secundárias.

**Ponte manual — decisão final, não a de fallback.** O usuário optou por **nunca usar `ANTHROPIC_API_KEY` no dia a dia** — toda passada de IA é feita por um chat do Claude Code lendo o RUNBOOK.md e seguindo o mesmo `bridge.py`/`pacote.md`/`colar-resposta` que a ponte manual já previa, só que como caminho único, não alternativo. Isso zera o custo (`via="manual"`, `custo_usd=0`, ocupa a assinatura, não a API metered) e é o motivo de existir `.claude/skills/processar-aula/` e o RUNBOOK.md, que **precisam** ganhar uma seção nova toda vez que uma fase futura envolver IA. `server/app/routes/lessons.py` etapa 1 do runbook (achar aula pendente de processar) **exige `Transcript.aprovado_em` preenchido** — a fase 6 nunca processa uma transcrição que ainda não passou pela revisão humana da fase 5b.

**Guia de aula — artefato extra, não previsto originalmente, complementar à aula editada.** `Lesson.guia_md` (markdown corrido, sem schema): reorganiza a transcrição em seções legíveis preservando a voz do professor, sem os blocos tipados/`deriv_key` da aula editada — de propósito, porque esse conteúdo permite reordenar raciocínio dentro de uma seção (conceito → explicação → exemplo), o que quebraria a garantia de bloco = intervalo tocável que a aula editada carrega. Regenerado por inteiro a cada passada (sem reconcile). Traz também uma seção **"Árvore de conhecimento"** logo após o título — lista aninhada da hierarquia de classificações que o professor efetivamente construiu na aula (nunca completada com taxonomia "padrão" da doutrina). Visualização em `/guia` (renderizado com `python-markdown`) e download em `/guia.md`.

**A partir da fase 6 revisada: uma leitura só gera os dois.** Originalmente o guia nascia de uma **segunda chamada** (`server/app/ai/guia.py`, prompt próprio, pacote/colagem próprios em `/guia-pacote.md`/`/colar-guia`) — lendo a transcrição inteira de novo do zero. Isso foi corrigido: `guia_md` virou mais um campo de `LessonProcessingOutput` (junto de `resumo`, `aula_editada`, `cards`...), as instruções do guia entraram em `bridge.py` ao lado das demais, e `_ingest()` grava `Lesson.guia_md` na mesma passada que grava o resto. Sem chamada extra, sem pacote extra, sem colagem extra — `server/app/ai/guia.py` não existe mais. Ver "Decisões fechadas" para o porquê.

**7. Revisão espaçada, calibração e offline** — SM-2, fila diária **intercalando matérias por padrão**, contagem por matéria, atalhos `1–4` no desktop. Errou o card → botão que toca os 30s de origem. Marcação de confiança antes de revelar (*chutei · acho que sei · tenho certeza*) e painel de calibração mostrando o acerto real dentro de cada nível. **Cache offline da fila do dia** no PWA, com as respostas sincronizando quando a rede volta — revisar no ônibus é justamente onde sobra tempo, e é onde a rede falha.

Aqui entra também a decisão sobre cards pendentes: eles chegam como **propostas** e a fila de revisão nunca fica vazia por falta de aprovação — há **aceitar todos** na tela de aprovação, e uma semana corrida sem aprovar não quebra o hábito de revisar o que já está ativo.

**Limite diário e modo recuperação — o que impede o sistema de morrer.** A forma clássica de abandono de revisão espaçada é sumir cinco dias e voltar para 190 cards vencidos: a fila vira dívida impagável e você desiste dela. Então há um **teto diário configurável**, e depois de uma ausência a fila entra em **recuperação** — prioriza o que está mais atrasado, o que você mais erra e o que cai na prova mais próxima, distribuindo o resto pelos dias seguintes em vez de despejar tudo de uma vez. Uma semana ruim atrasa o cronograma; não quebra o hábito.

**Modo prova.** Faltando dois dias para Civil, você não quer os 12 cards que venceram hoje — quer varrer **todo o escopo**. O modo intensivo ignora o agendamento e percorre o escopo da prova por ordem de fraqueza (menor taxa de acerto e confiança mal calibrada primeiro), sem estragar o agendamento normal depois. É justamente quando o app mais seria usado.

**8. Assuntos e estudo ativo** — os **assuntos propostos pela IA** (campo já vindo da fase 6) entram na tela de aprovação, com **fundir · renomear · separar** desde o começo; `assunto` global e `assunto_cobertura` datada por matéria e semestre; `window.py` passa a **atravessar aulas** seguindo o vínculo do assunto. Junto: **cloze** na aula editada e **cards de discriminação** a partir dos pares extraídos, com comparação lado a lado e áudio dos dois momentos. Painel de **gasto acumulado** lendo `ai_call`, com aviso antes de lotes grandes e teto mensal.

> **Status:** dividida em duas entregas, seguindo a própria costura da seção *Verificação* (item 15b separado do 16). **8a — feito**: `Assunto`/`AssuntoCobertura`/`LessonAssunto`, fundir/renomear/separar, `/assuntos` e página do assunto (termos/artigos/material ficam placeholder até as fases 9-12 existirem), `window.py` (simplificado: recorta a aula inteira vinculada ao assunto, não um trecho dela — o campo `assunto` ainda não marca onde começa/termina dentro de uma aula), painel de gasto (`/admin/gasto`). **8b — feito**: cloze na aula editada (`server/app/study/cloze.py`, botão "Modo estudo" em `/lessons/{id}/aula-editada`, só nos blocos `ditado`/`conceito`) e cards de discriminação a partir de `pares_confundiveis` — persistidos como `CardProposal` com `tipo="discriminacao"` (mesma tabela, mesma fila SM-2, seção própria na aprovação), com comparação lado a lado e áudio dos dois momentos quando a IA identifica o intervalo de cada termo (`start_s_a/b`, `end_s_a/b`, adicionados ao schema nesta fase — ver RUNBOOK.md). Fecha a Entrega B.

---

### Entrega C — Corpus

*Fim da entrega: tudo que você lê está dentro do sistema, marcado pelo glossário e achável numa busca só.*

**9. Materiais e Google Docs** — a tabela `material` como **fonte única para tudo que não é áudio**: PDF, texto, link e Google Doc (`origem = gdoc`). Sync do Drive por Service Account, incremental por `modifiedTime`, HTML→Markdown, vinculação automática doc↔aula, caixa de "Não vinculados", página de estado. Tipos e tags, `material_use` com intervalo, e os botões *Ver aqui* (`/preview` embutido) e *Criar doc desta aula* pelo link de cópia de modelo.

> **Status: feito.** `Material`/`MaterialUse`/`MaterialTag`/`MaterialTipo` (seed com o vocabulário do PLANO.md), `Subject.drive_folder_id`/`doc_modelo_id`. `server/app/library/gdocs.py` (cliente injetável — `FakeGoogleDriveClient` cobre todos os testes, `RealGoogleDriveClient` usa Service Account e só é exercitado com `GOOGLE_SERVICE_ACCOUNT_JSON` configurado — **ainda não testado contra a API real nesta sessão**, sem credencial disponível) + `sync_drive_folder` (incremental, comparação tolerante a timezone porque o SQLite não guarda tzinfo). `library/matcher.py` (por pasta → matéria; por data no nome do arquivo ou proximidade com `modified_time` → aula; ambíguo não resolve sozinho) e `library/html_to_md.py` (`markdownify`). `/materials` (lista, "Não vinculados", cadastro manual pdf/foto/texto/link, botão "Sincronizar agora"), `/materials/{id}` (detalhe, tags, tipo, "Ver aqui" via iframe do `/preview` nativo do Docs), `/lessons/{id}` ganhou a lista de materiais vinculados e o botão "Criar doc desta aula". **Deliberadamente fora do escopo**: indexar materiais na busca (`chunk`/`chunk_fts` é fase 12 — indexar agora seria fazer parte da fase 12 cedo demais e reindexar de novo depois); extração de conteúdo de PDF/foto (fase 10, visão); `pagina_inicial`/`pagina_final` em `MaterialUse` já existem na tabela (nulos) pra fase 10 não exigir outra migração, mas nada ainda os preenche.

**10. Biblioteca — livros, visão e citação** — **fotos de páginas** e PDF escaneado indo para **transcrição por visão**, com botão de **refazer aquela página** (marcar como erro e retranscrever); várias fotos formando um material único com ordem, e a **imagem de cada página guardada** para o *▸ ver a página original*. Numeração com **deslocamento arquivo→obra**; **obra bibliográfica permanente** com capa, contracapa, folha de rosto e ficha catalográfica e campo de **referência manual**; **estrutura por sumário**, porções encaixando por intervalo de páginas, mapa de cobertura e aviso de sobreposição; **marcação de trechos por matéria com intervalo**, acumulável ao longo dos anos e usada como escopo na geração de estudo; estante com as capas; **copiar citação em ABNT** com a página certa; e a **tela de leitura do material** — capítulo corrido com marcador de página, texto editável com proteção contra sobrescrita, e botão de **baixar** (`.md`/`.txt` com a referência no cabeçalho).

> **Status: núcleo feito, com um desvio deliberado do desenho original.** **A transcrição por visão NÃO usa a API da Anthropic** (`claude-haiku-4-5` como o texto acima previa originalmente) — decisão do usuário, mesma lógica do resto do app: o Claude Code lê a foto direto com o Read tool (que já lê imagem nativamente) e devolve pela ponte manual, sem chamada paga nenhuma. `server/app/library/vision.py` (o stub injetável que existia pra isso) foi removido; no lugar, `.claude/skills/transcrever-paginas/SKILL.md` + `transcrever-paginas.ps1`/`.bat` (mesmo mecanismo do `processar-aulas`, ver "Ponte manual" acima) — RUNBOOK.md, seção "Fase 10 — Transcrever páginas de livro". **Sem portão de aprovação antes de transcrever** (diferente de áudio): você já escolheu a foto, a curadoria da fonte já aconteceu no upload — `MaterialPage.status="pendente"` significa só "ainda não transcrita".
>
> Modelos: `Work`/`WorkImage`/`WorkSection`/`MaterialPage`, `Material` ganhou `work_id`/`pagina_inicial`/`pagina_final`/`ordem_manual`, `MaterialUse` ganhou `lido_ate`. `library/pdf.py` (pypdf + PyMuPDF): cada página do PDF é decidida individualmente — com camada de texto extrai na hora (`extraido_por="nativo"`, `status="ok"`, sem custo); sem texto (escaneada) renderiza como PNG e cai no mesmo caminho de uma foto (`status="pendente"`). `library/abnt.py` monta a referência a partir dos campos da obra (`referencia_manual` sempre sobrepõe). `library/coverage.py` calcula o mapa de cobertura na hora, comparando `WorkSection` contra os materiais já subidos — nada é guardado. `library/ingest.py::find_overlapping_materials` bloqueia upload com intervalo de página colidente a menos que você confirme explicitamente ("sobrepor mesmo assim").
>
> **Bug real encontrado e corrigido nesta fase:** `Content-Disposition` com o título da obra acentuado quebrava o download (mesma família do já documentado "curl com argumento inline" do RUNBOOK.md, só que do lado do servidor desta vez) — corrigido replicando a lógica RFC 6266 que o próprio `FileResponse` do Starlette usa (`filename*=utf-8''<percent-encoded>`).
>
> **Deliberadamente fora do escopo desta passada** (fica pra quando fizer falta de verdade, sem exigir nova migração): preenchimento automático da ficha catalográfica a partir da foto (hoje formulário manual); extração automática da estrutura a partir da foto do sumário (hoje `WorkSection` é cadastro manual — a mesma skill de transcrever páginas poderia ganhar esse modo depois); marcação do glossário no texto (depende do glossário existir, fase 11); botão "copiar" (só "baixar" existe); tela de leitura lado a lado foto+texto em tela larga (hoje é um toggle que mostra a imagem abaixo, não lado a lado); `MaterialUse.lido_ate` existe na tabela mas nenhuma tela ainda grava nele.

**11. Glossário** — **único para todo o curso**, atravessando matérias e semestres. Três partes:
- *Captura*: definições propostas pela IA na mesma tela de aprovação, anexadas ao termo existente quando a grafia já existe; criar definição a partir de qualquer seleção de texto, em qualquer fonte.
- *Leitura*: marcação em **todo texto do app** em tempo de renderização, com índice Aho-Corasick sobre as variantes (uma passada, independente do tamanho do glossário); primeira ocorrência por bloco, pontilhado discreto, interruptor global e chave por verbete para parar de destacar termos genéricos; card sobreposto com **todas as definições do termo** — matéria, professor, data, citação e **botão de tocar o trecho** —, ordenadas pelo teor do texto lido, com opção de fixar a preferência.
- *Aba própria*: lista com busca instantânea, filtro por matéria e por pendentes; página do termo com histórico cronológico; e as ferramentas de correção — adicionar/editar variantes, corrigir grafia, editar definição, **fundir** termos quase-duplicados, separar, descartar definição. Gerar cards por definição num clique.

> **Status: núcleo feito e testado contra o staging real.** Modelos: `Term`/`TermAlias`/`Definition`/`TermPin` (`server/app/models.py`) — mesmo padrão de Assunto (entidade global casada por slug + tabela datada). `Definition.term_id` nasce **nulo** numa proposta da IA (mesmo adiamento de `LessonAssunto.assunto_id`): o texto proposto (`termo_proposto`) e as variantes (`variantes_propostas_json`) ficam editáveis na tela de aprovação, e só viram `Term`/`TermAlias` de verdade na aceitação (`/lessons/{id}/termos/{id}/aceitar`, em `routes/ai.py`, ao lado do aceitar de assunto) — evita grafia errada da IA poluindo o glossário global antes de você poder corrigir.
>
> `glossary/normalize.py` (normalização preservando o comprimento de cada caractere, pra offset de regex bater com o texto original sem remapear), `glossary/matcher.py` (uma regex de alternação, ordenada por comprimento decrescente — "Aho-Corasick" do PLANO.md é isto, não um autômato de verdade; documentado como simplificação deliberada dado o volume real de termos de um curso), `glossary/render.py` (percorre só nós de texto via `html.parser.HTMLParser`, nunca o interior de tag), `glossary/index.py` (monta a lista de variantes ativas do zero a cada render — sem cache em memória; reversível se a escala um dia doer), `glossary/merge.py` (fundir/separar/achar-ou-criar, reaproveitando `assuntos.normalize_slug`). `routes/glossary.py` cobre a aba `/termos`: lista com busca e três ordenações, filtro `?pendentes=1` (fila de propostas de todas as aulas num lugar só), página do termo, renomear (só o rótulo, mesma regra do assunto), destacar on/off, variantes, fundir, criar na mão, editar/descartar definição, separar, fixar/desfixar preferência por matéria.
>
> **Onde a marcação já está ligada:** aula editada (`edited_lesson.html`, sobre o texto puro OU já processado pelo cloze — a mesma função de highlight roda por cima dos dois, já que ela só toca nós de texto) e leitura de obra (`work_read.html`). O termo marcado é um `<span class="glossary-term" data-term-id="N">`; um clique navega para `/termos/{id}` via JS simples — **não** é o card sobreposto (popover sem sair da página) que o PLANO.md desenha; isso fica pra quando a UI de card flutuante existir de verdade.
>
> **Bug real encontrado e corrigido durante esta fase** (achado numa limpeza manual de dado de teste, não num teste automatizado): `Lesson` não tinha relação de cascade de volta pra `Definition` — `Term.definitions` já cascateava a partir do termo, mas apagar uma `Lesson` com termos propostos vinculados quebrava com `FOREIGN KEY constraint failed`, porque nada dizia ao SQLAlchemy pra apagar/desvincular a `Definition` primeiro. Corrigido com `Lesson.definitions` (cascade="all, delete-orphan"), espelhando as outras seis relações que `Lesson` já tinha pra `EditedBlock`/`CardProposal`/etc.
>
> **Deliberadamente fora do escopo desta passada:** campo "professor" (o mockup mostra `Prof. ___`, mas não há coluna nem no `Subject` nem no `Definition` — mostra matéria + aula, sem nome de professor); `tipo(definiu|refinou)` em `Definition` (a ordem cronológica na página do termo já comunica isso sem precisar de campo novo no schema da IA); **interruptor global** de destacar na barra (só o botão por verbete existe); ordenação de definições por "proximidade de vocabulário com o parágrafo em volta" (a heurística de peso automático do PLANO.md) — hoje é cronológica simples, com fixar manual (`TermPin`) sobrepondo quando você quiser resolver na mão; "gerar card a partir de uma definição" num clique (a definição já pode virar card manualmente, mas não há botão dedicado ainda); marcação em transcrição bruta e em anotações (anotações ainda não existem como conteúdo — chegam em fase futura; transcrição bruta é fonte, nunca teve marcação de leitura); integração com `chunk_fts`/busca (explicitamente fase 12, conforme a separação do próprio PLANO.md).

**12. Busca unificada e página do assunto** — `chunk_fts` cobrindo transcrição, materiais (incluindo Docs e livros), observações e definições, com **filtros por tipo de fonte** e etiqueta de procedência em cada resultado, filtro por matéria e período, e o termo casado **fixado no topo** (casando também pelas variantes). Cada resultado volta à origem certa: minuto do áudio, página da obra com *copiar citação*, ou o Doc no editor.

E a **página do assunto**, que só faz sentido depois que os livros existem: aulas que o cobrem (de qualquer semestre), trechos de obra marcados, suas anotações, termos relacionados, artigos, cards com taxa de acerto e quando você estudou pela última vez. É onde Civil I e Civil III se encontram.

> **Status: núcleo feito e testado contra o staging real.** Em vez de um único `chunk_fts` guardando conteúdo heterogêneo, cada fonte ganhou sua própria tabela FTS5 externa — mesmo padrão de `transcript_fts` (fase 5) repetido quatro vezes: `material_fts` (`Material.conteudo_md` — cobre texto colado e Docs sincronizados), `material_page_fts` (`MaterialPage.texto` — páginas de obra), `edited_block_observacao_fts` (`EditedBlock.observacao` — suas anotações na aula editada) e `definition_fts` (`Definition.definicao_md` — glossário). "`chunk_fts` cobrindo tudo" do texto acima é a ideia; quatro índices dedicados é a implementação — SQLite FTS5 externo só aceita uma tabela de conteúdo por índice, e distinguir a fonte é exatamente o que o filtro "tipo" precisa fazer de qualquer forma. Diferente da transcrição (só INSERT/DELETE, nunca UPDATE — reprocessar apaga e recria o segmento), estas quatro fontes SÃO editadas no lugar, então cada uma ganhou também um trigger `AFTER UPDATE` (apaga a linha velha do índice, insere a nova — receita padrão do próprio SQLite pra FTS5 de conteúdo externo mutável) — `server/migrations/versions/0015_unified_search.py`.
>
> `routes/search.py` roda as cinco buscas (transcrição + as quatro novas) e combina os resultados por `bm25` num só `ORDER BY` em Python — os escores não são perfeitamente comparáveis entre tabelas FTS5 diferentes (não é um índice único de verdade), mas com o mesmo tokenizador em todas, a ordenação combinada já é boa o bastante pra um app de uma pessoa; documentado como simplificação deliberada. Filtro por matéria funciona nas cinco fontes (material/página de obra via `EXISTS` em `MaterialUse`, o resto via `subject_id` direto); filtro por período (data) só se aplica a fontes com data de origem confiável (transcrição, observação, definição-com-aula) — material solto e página de obra não têm uma data própria, então ignoram esse filtro (documentado no código). **Termo fixado no topo**: compara a busca inteira, normalizada (`glossary/normalize.normalize_char_preserving`), contra o rótulo e cada variante de cada `Term` — casamento exato na grafia normalizada, não substring, pra "usucapião" não fixar todo termo que contém a palavra.
>
> **Cada resultado volta à origem certa**: transcrição → `/lessons/{id}/transcricao?t={s}` (já existia); material → `/materials/{id}`; página de obra → `/works/{id}/ler#pagina-{id}` com um botão **📋 copiar citação** que chama a rota `/works/{id}/citar` já existente da fase 10 (criada mas nunca ligada a um botão até agora); observação → `/lessons/{id}/aula-editada#bloco-{id}` (o bloco ganhou `id` só agora, pra isso funcionar); definição → `/termos/{id}`.
>
> **Página do assunto**: as três seções derivadas de `lesson_id` sem tabela de vínculo nova — **termos relacionados** (`Term` com `Definition` ativa em alguma aula do assunto), **artigos citados** (`ArticleMention` das mesmas aulas) e **material** (`MaterialUse.lesson_id` nas mesmas aulas) — substituem o placeholder que já dizia "chegam nas fases 9–12" desde a fase 8. **Deliberadamente fora do escopo**: "trechos de obra marcados" e "suas anotações" na página do assunto — nenhum modelo hoje liga uma `WorkSection`/trecho de obra ou uma anotação a um `Assunto` especificamente (só a uma matéria inteira, via `MaterialUse`/`Term`); criar esse vínculo seria uma escolha de design nova (marcação manual? automática por matéria+palavra-chave?) que o PLANO.md não especifica — melhor decidir isso quando "anotações" existir como conteúdo de verdade (ainda não existe, ver status da fase 11) do que inventar um mecanismo agora só pra preencher a seção.

---

### Entrega D — Treinar

*Fim da entrega: você produz — falando e escrevendo — e chega na prova com um plano.*

**13. Produção — Feynman e dissertativa** — gravação curta no navegador; `shortasr.py` com `faster-whisper small` na **CPU da VPS** (independente do seu PC estar ligado); comparação com a definição do professor, apontando o que faltou e linkando o minuto. Dissertativa: geração da questão com rubrica, campo de resposta, correção com feedback e histórico de tentativas. Ambas com **copiar prompt / colar resposta** ao lado do botão automático — são as duas ações em que você está sentado estudando, onde o modo manual é mais natural.

> **Status: núcleo feito e testado contra o staging real.** Modelos: `FeynmanAttempt` (`term_id`, áudio, transcrição, avaliação), `DissertativaQuestion`/`DissertativaAttempt` (histórico de tentativas — nunca sobrescreve, cada resposta é uma linha nova, mesma lógica de `ReviewLog`). Nenhuma das três usa `deriv_key`/`reconcile`: não são derivadas de reprocessamento de transcrição, são suas próprias tentativas.
>
> **A transcrição do Feynman é sempre automática, nunca ponte manual** — é a única passada de IA do app com essa exceção. `faster-whisper small` (`WHISPER_SHORT_MODEL`) roda na CPU da VPS via `app/media/asr.py` (`RealASRClient`, injetável — mesma interface `ASRClient`/`FakeASRClient` que já existia desde antes desta fase, esperando por ela), reaproveitando `shared/transcriber.py::WhisperTranscriber`, o mesmo wrapper da válvula de emergência "transcrever na VPS agora" (fase 4) — só com modelo pequeno em vez de médio, porque ~60s de fala precisam sair em segundos, e a precisão importa menos aqui: a IA que avalia depois compara **sentido**, não usa a transcrição como fonte de estudo. Só a AVALIAÇÃO (comparar a explicação contra a(s) definição(ões) do termo) é uma chamada de IA de verdade, e essa sim segue a ponte manual — pacote/colar-resposta, como todo o resto do app. Comparado contra **todas** as definições ativas do termo, não uma só ("todas as definições, lado a lado" vale aqui também).
>
> **Dissertativa tem duas fontes de geração, cada uma com seu próprio pacote/colar**: uma aula (`build_context_for_lesson`, a transcrição literal daquela aula) ou um assunto inteiro (`context/window.py::build_context_for_assunto`, já existia desde a fase 8a — a mesma concatenação de todas as aulas vinculadas, reaproveitada sem mudar nada). `DissertativaQuestion.subject_id` é **nulo** quando a questão vem de um assunto (assunto é global, atravessa matérias — não existe "a matéria certa" pra forçar ali) e preenchido com a matéria da aula quando vem de uma aula. Responder uma questão (`POST /dissertativas/{id}/responder`) não custa nada — só grava a tentativa; corrigi-la é que aciona a ponte manual, por tentativa.
>
> **Atenção, não bug:** `lesson_detail.html` mostra "Baixar pacote (.md)"/"Colar resposta" (fase 6) como `<span>` desabilitados, não links — parecia um regresso ao primeiro olhar, mas há teste cobrindo exatamente isso (`test_lesson_detail_shows_processing_buttons_disabled_when_transcribed`): decisão do usuário, "temporária", as rotas continuam existindo e respondem por curl/skill normalmente, só a UI não oferece o clique. Confirmado com o usuário que isso **não** se estende aos botões novos desta fase — Feynman e dissertativa ficam como links de verdade, clicáveis, porque não têm um atalho automatizado equivalente (`processar-aulas.ps1`) puxando o mesmo fluxo.
>
> **Deliberadamente fora do escopo desta passada:** card sobreposto lado a lado pra dissertativa/Feynman (hoje é página própria, não popover — mesma simplificação já assumida pelo glossário na fase 11); nota numérica na correção da dissertativa (o schema tem `pontos_cobertos`/`pontos_faltantes`, sem "nota de 0 a 10" — decidir a métrica antes de ter dado real de uso seria inventar um número sem base); "linkando o minuto" nas divergências específicas do Feynman (o card mostra as definições inteiras com botão ▸ ouvir cada uma, não um link por ponto individual da avaliação — pedir que a IA devolva um `definition_id`/timestamp por ponto arriscava referência inventada, e o ganho de UX era pequeno pra esse risco).

---

**14. Provas, plano regressivo e exportação** — cadastro **opcional** da ementa oficial, que apenas enriquece os assuntos já emergidos das aulas (ordem e títulos oficiais) em vez de ser pré-requisito; entidade `exam` com data e escopo por assunto; e o painel que fecha o ciclo: dias restantes, cobertura, cards vencidos no escopo, ritmo necessário por dia e os assuntos com pior desempenho.

**Exportar e imprimir**: aula editada e apanhado do escopo da prova em PDF para estudar no papel na véspera; **bibliografia** em ABNT das obras usadas, para colar no trabalho ou no TCC; e **exportação do corpus inteiro** — árvore de Markdown com aulas, transcrições, aula editada, glossário, assuntos, materiais e cards. Backup protege contra a VPS morrer; isso protege contra você querer sair do app, e é a diferença entre um sistema e uma prisão.

> **Status: núcleo feito e testado contra o staging real.** Modelos: `Ementa`/`EmentaTopico` (uma ementa por `Subject`, tópicos recriados a cada reimportação), `Exam`/`ExamScope` (N:N simples com `Assunto`). Nenhuma passada de IA nesta fase — sem seção nova no RUNBOOK.md.
>
> **PDF sem dependência nova**: em vez de trazer `weasyprint`/`reportlab` (a primeira exige libs de sistema — Cairo, Pango — mudando a imagem Docker), `app/export/pdf.py` usa `fitz.Story` do próprio PyMuPDF, dependência da fase 10 (`library/pdf.py`) — lê HTML+CSS simples e resolve paginação sozinho. Verificado gerando PDF de verdade (cabeçalho `%PDF-`) tanto em teste quanto contra o staging.
>
> **Ementa enriquece sem rebaixar nem renomear**: `ementa.py::import_ementa` casa cada tópico com um `Assunto` por slug (`find_or_create_assunto`, mesma função de sempre); se a cobertura já existe (de aula, `origem="ia"/"manual"`), só ganha `ordem` -- nunca perde `status="dado"` nem tem o título do assunto sobrescrito por engano. Um tópico sem nenhuma aula ainda vira um `Assunto` novo com `AssuntoCobertura.status="pendente"` -- "na ementa, mas ainda não dado". Reimportar substitui a lista de `EmentaTopico` inteira (mesma `Ementa`, nunca duplica a linha).
>
> **`AssuntoCobertura.status` fica em dois valores guardados** (`pendente`/`dado`), não três: "estudado" do mockup do PLANO.md (`status(pendente|dado|estudado)`) é **computado** no painel a partir de `ReviewLog` (tem pelo menos uma revisão registrada nos cards das aulas daquele assunto), não gravado -- evita acoplar o fluxo de revisão espaçada (fase 7) a escrever num campo de um assunto toda vez que você responde um card, e o painel já precisa fazer essa consulta de qualquer jeito pra calcular "mais fraco em".
>
> **`study/exam_panel.py::compute_exam_panel`** calcula tudo na hora, nada guardado: dias restantes (`exam.data - hoje`), cobertura (`dado`/total do escopo), estudados (contagem acima), sem material (zero `MaterialUse` nas aulas do assunto), cards vencidos no escopo (união dedupada por `id`, não por assunto -- o mesmo card não conta duas vezes se, por algum motivo, aparecesse em dois assuntos), ritmo necessário (`ceil(vencidos / dias_restantes)`) e os 3 assuntos com menor taxa de acerto entre os que já têm pelo menos uma revisão (sem revisão nenhuma não é "fraco", é "ainda não estudado" -- categoria diferente, não misturada na lista).
>
> **Exportação**: `/lessons/{id}/aula-editada.pdf` (reaproveita o mesmo `highlight_html`/glossário da tela, sem os elementos interativos); `/exams/{id}/apanhado.pdf` (por assunto do escopo, o `guia_md` de cada aula vinculada -- o guia já É a versão condensada e legível, reconstruir algo novo a partir dos blocos crus seria duplicar trabalho); `/subjects/{id}/bibliografia.txt` (agrega `library/abnt.py::build_reference` de toda obra usada na matéria, dependência já existente da fase 10); `/export/corpus.zip` (árvore de `.md` puros -- `zipfile` da stdlib, sem biblioteca nova -- com pasta por matéria/aula: transcrição, aula editada, guia, mais `glossario.md`/`assuntos.md`/`materiais.md`/`cards.md` globais).
>
> **Bug real encontrado e corrigido testando contra o staging real:** `ensure_cobertura` (já existia desde a fase 8) só sabia "se já existe, não toca em nada" -- correto pra impedir a ementa de rebaixar uma cobertura "dado" de volta pra "pendente", mas isso também impedia a promoção inversa: aceitar a proposta de assunto de uma aula pra um tópico que a ementa já tinha marcado "pendente" deixava a cobertura pendente **pra sempre**, mesmo já dada de verdade. Corrigido: agora `ensure_cobertura` promove "pendente" -> "dado" quando chamada com `status="dado"` (o caso de aceitar aula), mas continua nunca rebaixando "dado" -> "pendente" (o caso de importar ementa).
>
> **Deliberadamente fora do escopo desta passada:** vínculo "estudado" gravado (ver acima); reordenar `Assunto` globalmente pela ordem da ementa (a ementa é por `Subject`, um assunto pode ter ordens diferentes em ementas de matérias/semestres diferentes -- `ordem` mora em `AssuntoCobertura`, não em `Assunto`, de propósito); edição da lista de tópicos linha a linha (hoje é recolar o texto inteiro pra reimportar -- editar/reordenar um tópico só ainda não tem tela própria); PDF com fonte/diagramação além do CSS mínimo embutido em `pdf.py` (sem seletor de tema, sem capa).

**15. Mapa e destaques em áudio** — renderização do Mermaid com nós ligados ao glossário; corte dos clipes de 30s com ffmpeg a partir do mp3 e dos timestamps dos blocos, fila tocável com Media Session e tela bloqueada.

> **Status: núcleo feito e testado contra staging + ffmpeg real.** `Lesson.mapa_mermaid` (fase 15) recebe o campo `mapa_mermaid` que `LessonProcessingOutput` já tinha desde a fase 6, só guardado cru até agora — mesmo padrão do resumo/guia: regenerado por inteiro a cada reprocessamento, sem `deriv_key`.
>
> **Mermaid renderizado no navegador, sem CDN em tempo de execução**: em vez de um `<script src="https://cdn...">` (dependência de rede toda vez que a página carrega — o app roda em Wi-Fi de faculdade, não pode depender disso), `server/app/static/mermaid.min.js` é o bundle da mermaid.js **auto-hospedado** (baixado uma vez durante o desenvolvimento, servido como qualquer outro asset estático) — nem CDN em produção, nem dependência Python nova, nem passo de build. `/lessons/{id}/mapa` renderiza `<pre class="mermaid">{{ mapa_mermaid }}</pre>` e chama `mermaid.initialize({ securityLevel: "loose" })` (precisa de "loose" pra `click` funcionar).
>
> **Nós ligados ao glossário**: `glossary/mermaid.py::link_mermaid_nodes_to_glossary` não é um parser de gramática Mermaid completo -- reconhece por regex o padrão comum de nó (`Id[Rótulo]`, `Id(Rótulo)`, `Id{Rótulo}`, `Id([Rótulo])`, `Id[[Rótulo]]`), casa o rótulo contra o glossário (mesmo `normalize_char_preserving`/`load_active_variants` da fase 11) e injeta linhas `click Id "/termos/{id}" "_self"` no fim do texto Mermaid antes de renderizar — simplificação deliberada, suficiente porque a IA sempre gera o mesmo estilo de flowchart simples pedido no prompt.
>
> **Destaques em áudio**: `shared/audio.py` ganhou `cut_clip` (mesmo módulo/convenção do worker e da válvula de emergência da fase 4 -- `-c copy`, sem reencodar, corte é pra audição casual, não edição de precisão). `/destaques` lista os blocos `destaque-prova`/`ditado` das últimas aulas (as 30 entradas mais recentes, todas as matérias juntas — "você já ouve aula no ônibus"); `/destaques/{block_id}/clip.mp3` corta sob demanda a partir do mp3 já comprimido da aula (nunca do original, que a VPS já apagou) e cacheia em `DESTAQUES_CLIPS_DIR`, com o hash de `start_s`/`end_s` na chave do cache -- se a aula for reprocessada e os limites do bloco mudarem, o clipe velho nunca é servido por engano. Fila tocável em JS puro com Media Session API (`setActionHandler` pra play/pause/anterior/próximo, funciona com tela bloqueada e controles no fone) -- sem nenhuma biblioteca de player.
>
> **Dois bugs encontrados e corrigidos nesta fase.** (1) Pré-existente, não desta fase: o botão "Gerar de novo" em `guia.html` linkava pra `/lessons/{id}/colar-guia`, rota removida no merge da fase 6 (`test_guia.py` já cobria que a rota devolve 404, mas nada cobria o template continuar linkando pra ela) — trocado por um link de volta pra `/lessons/{id}`, onde reprocessar a aula inteira já vive. (2) Desta fase: `tests/conftest.py::app_env` isola `MEDIA_ORIGINAL_DIR`/`MEDIA_WEB_DIR`/`UPLOAD_STAGING_DIR`/`MATERIAL_FILES_DIR` num `tmp_path` descartável, mas `FEYNMAN_AUDIO_DIR` (fase 13) e `DESTAQUES_CLIPS_DIR` (esta fase) tinham ficado de fora dessa lista — rodar a suíte localmente escrevia áudio de verdade em `data/media/feynman/`/`data/media/destaques/` **dentro do repositório**, exatamente o problema que esse isolamento existe pra evitar (mesmo motivo do "lixo em `data/media/original/`" que o comentário do fixture já documentava). Corrigido adicionando as duas variáveis à lista; diretórios órfãos já criados localmente, removidos.
>
> **Deliberadamente fora do escopo desta passada:** duração fixa de 30s por clipe (o corte usa os limites reais do bloco -- `start_s`/`end_s` -- não um recorte de tamanho fixo; blocos `destaque-prova`/`ditado` tendem a ser curtos por como são gerados, então na prática já ficam perto disso); download do mapa como imagem/SVG (só a página renderizada, sem botão de exportar PNG); busca por termo dentro do mapa; PWA/Media Session testado num dispositivo real com tela bloqueada de verdade (testado via API do navegador, não numa sessão física de "celular no bolso").

### v2 — profundidade

**16. Artigos e legislação** — extração de citações, normalização com diploma padrão por matéria, página por artigo, filtro "aulas que citam art. X", ligação termo ↔ artigo, e sugestão automática de tópicos da ementa a partir das citações.

### v3 — depois

**Busca semântica** — embeddings ao lado do FTS5, para achar sem lembrar a palavra exata ("aquele exemplo do carro" achando um trecho que diz "veículo"). É o teto conhecido da busca lexical, e aparece com o tempo, não no primeiro semestre. Soma-se ao índice existente sem refazer nada.

Convite de acesso · importação de texto de lei (Planalto/LexML) ao lado do artigo · exportação `.apkg` pro Anki como escape hatch · síntese semanal conectando aulas e matérias · pré-questões antes da próxima aula · sessão de estudo guiada ("tenho 30 minutos").

---

## Verificação

Os itens estão agrupados pela entrega a que pertencem — **1 a 5b fecham a entrega A**, 6 a 11 a B, 12 a 15 e 21 a 21b a C, e o restante a D. Vale rodar o bloco de cada entrega antes de passar para a seguinte, em vez de deixar tudo para o fim.

1. `docker compose up` na VPS; abrir `https://drwyver.mecadosjogos.app.br/login`, entrar com `admin`/`admin` e confirmar que o cookie persiste depois de fechar o navegador. Cadastrar um segundo usuário em `/registrar`, confirmar que ele não consegue logar até aprovado em `/admin/seguranca`, aprovar com prazo e confirmar que expira sozinho depois do prazo.
2. Confirmar que as 5 matérias do semestre foram criadas pelo seed, e criar uma aula de **Teoria Geral do Direito Civil** com a data de hoje.
3. Do iPad, subir um áudio real pelo Atalho; confirmar que aparece como *aguardando worker*. Cortar a rede no meio de um upload e confirmar que ele retoma. Subir **dois arquivos marcados como uma aula única** (simulando o intervalo) e confirmar que a ordem é respeitada e a transcrição sai contínua, sem repetir nem perder o trecho da emenda.
4. Na máquina local, `ROLE=worker python -m worker.main --once`; confirmar no log: modelo em CUDA, progresso, upload do resultado. **Ligar os dois workers ao mesmo tempo** com várias aulas na fila e confirmar que nenhum pega o mesmo job e que a aula registra qual máquina a transcreveu. Com todos desligados, usar **transcrever na VPS agora** e confirmar que sai em ~40–60 min e fica marcada como versão de menor qualidade.
5. Confirmar na VPS: transcrição visível, mp3 em `media/web/`, **original apagado**, original presente em `archive/` no PC.
5b. **Backup e restauração** — o teste que ninguém lembra de fazer e que só importa quando já é tarde. Ligar o PC e confirmar que o worker puxou o dump sozinho, sem você pedir. Depois **ensaiar o desastre inteiro**: numa VPS limpa (ou num container novo), subir a aplicação vazia, usar **restaurar backup** enviando o arquivo do seu PC, e confirmar que aulas, transcrições, glossário, cards e o progresso de revisão voltam íntegros. Rodar **reconstruir mídia** e confirmar que os mp3 são regenerados a partir do `archive/` e voltam a tocar. Por fim, restaurar um backup **antigo** de propósito e confirmar que a comparação avisou antes, que a cópia de segurança do estado atual foi criada, e que dá para voltar atrás com ela. Backup não restaurado não é backup.
6. **Aula editada** — ela não é fonte de nada, mas é o que você vai ler toda semana, então vale conferir. Ler de ponta a ponta e comparar com a aula que você assistiu:
   - Está legível e organizada? Ficou mais curta que a transcrição sem perder conteúdo?
   - Uma ideia que o professor repetiu várias vezes aparece **uma vez, marcada como repetida** — não some nem aparece três vezes?
   - O que ele mandou anotar virou bloco `ditado`? O que ele disse que cai virou `destaque-prova`?
   - Escolher **3 blocos ao acaso** e tocar ▸ ouvir o original: o professor disse mesmo aquilo? Nada inventado, nada distorcido?
   - A transcrição bruta continua íntegra na aba ao lado?
7. **Resto da IA**: resumo bate com a aula, timestamps do índice caem nos trechos certos, cards são respondíveis sem contexto extra. Aprovar alguns e descartar outros.
8. **Recorte de contexto** — a regra que substitui o risco de paráfrase, então precisa ser verificada de verdade: pedir "mais cards deste tópico" e conferir no log que a chamada mandou **o trecho literal da transcrição** naquele intervalo (2–5k tokens), não a aula editada e não as duas horas. Conferir que o trecho enviado cobre o tópico inteiro, sem cortar o começo ou o fim da explicação.
9. **Citações de baixa confiança**: numa aula em que o professor citou vários artigos, confirmar que os de baixa confiança aparecem marcados; tocar o áudio de um deles, corrigir o número e confirmar que a correção se propaga para a citação e para os cards que a usam — e que ele não pergunta de novo depois de confirmado.
10. Verificar em `ai_call` que o custo da aula bate com a estimativa de ~US$ 0,45, e confirmar via `usage.cache_read_input_tokens` que uma segunda chamada sobre o **mesmo tópico** lê do cache.
11. **Ponte manual** — testar o caminho inteiro, ida e volta: numa aula ainda não processada, usar **baixar pacote**, arrastar o `.md` no seu Claude, e colar a resposta de volta; confirmar que a aula editada, os termos e os cards entram iguais aos da via automática e caem na mesma tela de aprovação. Depois testar a versão curta: **copiar prompt** numa dissertativa, colar a correção de volta e conferir que o histórico registra `via = manual` e custo zero. Colar de propósito uma resposta com conversa em volta do bloco JSON e confirmar que o parser ainda extrai. Colar algo inválido e confirmar que ele avisa em vez de gravar lixo.
12. **Glossário**: confirmar que a IA capturou apenas termos que o professor *definiu* (não os que só mencionou); aprovar alguns; reabrir a transcrição e confirmar que aparecem sublinhados, **só na primeira ocorrência de cada bloco**, e que tocar abre o card sem trocar de página e toca o áudio no ponto certo. Cadastrar "culpa" em TGC e depois em TGDC e confirmar que **as duas definições vão para o mesmo termo** (não criam dois verbetes) e que o card mostra ambas com sua procedência. Abrir o mesmo termo dentro de uma aula de TGC e dentro de um capítulo de livro de responsabilidade civil, e confirmar que **a ordem muda conforme o texto**. Confirmar que um termo definido em TGDC aparece marcado numa aula de **outra matéria** — é o ponto do glossário ser único. Desligar o destaque de um termo genérico e confirmar que ele some do texto mas continua no glossário e na busca. Adicionar uma terceira definição de refinamento e confirmar a ordem cronológica na página do termo. Testar plural e flexão ("negócios jurídicos" deve casar com "negócio jurídico"). Desligar o interruptor e confirmar que o texto volta ao normal.
13. **Correção do glossário**: na aba Termos, adicionar a variante "boa fé objetiva" ao termo "boa-fé objetiva" e confirmar que uma aula **já transcrita antes** passa a marcar o termo, sem reprocessar nada. Fundir dois termos quase-duplicados e confirmar que todas as definições e variantes migraram e que nenhum link antigo quebrou. Editar uma definição e confirmar que a citação literal e o link do áudio continuam intactos. Filtrar por "pendentes" e limpar a fila.
14. **Revisão, calibração e offline**: rodar a fila do dia, confirmar que ela **mistura matérias** por padrão, errar um card de propósito e confirmar que o botão toca o trecho de origem no minuto certo. Marcar "tenho certeza" e errar algumas vezes; confirmar que o painel de calibração reflete isso. Deixar cards pendentes de aprovação e confirmar que a fila **continua funcionando** com os já ativos. Depois: **colocar o celular em modo avião**, revisar a fila inteira, voltar a rede e confirmar que as respostas sincronizaram sem duplicar nem perder.
15. **Busca**: buscar um termo que exista só no áudio e outro que exista só nas anotações; confirmar que a mesma busca acha os dois com a fonte identificada e que o clique leva ao ponto certo. Confirmar que um acerto na transcrição **não aparece duplicado** pela aula editada, e que o clique abre o bloco editado correspondente. Buscar "negocios juridicos" — sem acento, no plural — e confirmar que o **termo aparece fixado no topo**, antes dos trechos.
15b. **Assuntos** — o teste que decide se o "unir infos antigas" funciona. Depois de processar 4 aulas, confirmar que a IA propôs assuntos coerentes e que aceitar leva um toque. Provocar o erro de propósito: aceitar "Capacidade" e "Capacidade de Fato" como dois e depois **fundir**, conferindo que aulas, cards e questões dos dois migraram. Numa aula que é continuação da anterior, confirmar que o mesmo assunto aponta para as duas e que pedir cards manda **os dois trechos**, não metade da explicação. Abrir a **página do assunto** e conferir que reúne aulas, trecho de livro marcado, anotações, termos, artigos e desempenho dos cards. Por fim, simular o semestre seguinte: criar uma matéria com `continua_de`, marcar que ela cobre um assunto já existente, e confirmar que a página passa a mostrar **as duas coberturas** sem duplicar o assunto.
16. **Estudo ativo**: no modo estudo da aula editada, confirmar que os trechos apagados são os que valem (ditado e conceito), não palavras aleatórias. Revisar um card de discriminação, errar de propósito e confirmar que ele mostra **o eixo da distinção** e o áudio dos dois momentos.
17. **Feynman por voz** — o teste que mais depende de acertar a régua: **com o PC desligado**, gravar 60s explicando um conceito pelo iPad e confirmar que transcreve na VPS em poucos segundos. Explicar deixando algo de fora de propósito e verificar se o feedback aponta exatamente aquilo, citando o minuto do professor. Depois explicar corretamente e confirmar que ele **não inventa uma crítica** — falso positivo aqui é pior que silêncio.
18. **Dissertativa**: gerar uma questão, responder de forma incompleta, conferir se a correção bate com a rubrica e cita a aula. Reler a rubrica e julgar se ela é justa — se não for, editar.
19. **Plano regressivo e exportação**: cadastrar uma data de prova com escopo por assunto — **sem cadastrar ementa nenhuma**, usando só os assuntos emergidos das aulas — e confirmar que dias restantes, cobertura, cards vencidos no escopo e ritmo diário fecham com a realidade. Depois cadastrar a ementa oficial e confirmar que ela **enriquece** (ordem e títulos) sem duplicar nem substituir o que já existia. Exportar o corpus inteiro e abrir a árvore de Markdown fora do app, conferindo que aulas, transcrições, glossário, assuntos e materiais estão legíveis sem o sistema.
20. **Mapa e destaques**: conferir se o diagrama da aula corresponde à taxonomia que o professor apresentou e se os nós abrem o verbete. Sair de casa com o celular, tocar a fila de destaques com a tela bloqueada e confirmar que os clipes cortam em pontos que fazem sentido.
20b. **Rede de conceitos**: na tela de uma matéria com aulas processadas, conferir a rede em nível de matéria — mais densa que a de aula. Na tela de uma aula, alternar entre o toggle "por aula"/"por bloco" e confirmar que o grafo troca sem recarregar a página, ficando mais esparso em "por bloco". Confirmar que um termo usado em mais de uma matéria aparece com a cor de destaque mesmo dentro da tela de uma matéria só, que pelo menos um par de discriminação aparece como aresta tracejada com o eixo da distinção no tooltip, e que clicar num nó Termo e num nó Assunto navega pra cada página de detalhe.
21. **Google Docs**: tocar em "Criar doc desta aula" no iPad e confirmar que o Google abre a cópia já nomeada e na pasta da matéria. Escrever um parágrafo novo nesse doc pelo iPad, rodar "Sincronizar agora" e confirmar que aparece na busca em segundos, vinculado à aula certa.
21a. **Biblioteca** — subir quatro coisas diferentes e conferir o ciclo inteiro: um **slide** do professor, um **capítulo com camada de texto**, um **capítulo escaneado** e **fotos de páginas tiradas na biblioteca**. Confirmar que escaneado e fotos foram para a transcrição por visão e ficaram pesquisáveis; comparar uma página transcrita com a imagem, incluindo **nota de rodapé e itálico de latim**, que é onde o erro se esconde; forçar uma página difícil e usar **refazer com modelo maior**, conferindo que só aquela página foi reprocessada e que o custo por página bate com a estimativa. Nas fotos: subir 14 páginas fora de ordem, ordenar, e confirmar que a sequência do texto sai correta. Abrir a **tela de leitura** e conferir o capítulo corrido com marcadores de página, glossário marcado e a foto ao lado; corrigir um erro de transcrição à mão, mandar **refazer com modelo maior** e confirmar que a página corrigida **não foi sobrescrita**. Usar **copiar** e colar num editor, e **baixar** o `.md` e o `.txt` conferindo que o cabeçalho traz a referência ABNT e o intervalo de páginas. Confirmar que nada apareceu na pasta sincronizada do Drive — e portanto que o capítulo não voltou como material duplicado na busca. Cadastrar a obra **fotografando a ficha catalográfica** e conferir campo a campo contra a página — autores, edição, local, editora, ano e ISBN; testar também uma obra com **organizador** e outra **traduzida**, que é onde a montagem automática falha, e usar o campo de **referência manual** numa delas confirmando que ele passa a ser o que o botão copia. Subir capa e contracapa e confirmar que a capa aparece na estante. Definir o **deslocamento de página** (arquivo começa na p. 247 do livro); buscar um trecho e conferir que o resultado mostra **a página da obra, não a do arquivo**, que o clique abre na página certa, que **▸ ver a página original** mostra a foto, e que **copiar citação** devolve a referência ABNT correta — conferir contra a folha de rosto do livro, que é onde o erro aparece. Buscar um termo que exista em aula e em livro e confirmar que os **filtros por tipo** separam os dois.
21b. **Livro ao longo do tempo** — o teste que só falha meses depois, então precisa ser simulado agora: fotografar o **sumário** e conferir que a estrutura de capítulos e páginas saiu correta. Subir o capítulo das p. 241–300 vinculado a TGDC/2026.1. Depois subir o das p. 1–120 e confirmar que ele **se posiciona antes** do primeiro sem nenhuma reordenação manual, e que o mapa de cobertura mostra o buraco das p. 121–240. Vincular uma porção a uma segunda matéria e confirmar que ela aparece nas duas **sem duplicar arquivo nem resultado de busca**. Depois o caso da Constituição: no mesmo arquivo, marcar **arts. 1º–4º para Ciência Política** e **art. 5º para Direitos Humanos**, e confirmar que pedir cards de Direitos Humanos gera **só a partir do art. 5º** — não do arquivo inteiro, não do capítulo inteiro. Conferir nos logs que a chamada mandou **o texto transcrito daquele intervalo**, e nenhuma imagem. Por fim, subir de propósito um capítulo que invade um intervalo já existente e confirmar que o aviso de sobreposição aparece antes de gravar.
21c. **Aula sem áudio**: criar uma aula de seminário sem gravação, anexar anotações e um PDF, e confirmar que ela participa da busca, do glossário e dos cards normalmente — sem quebrar nenhuma tela que espera um player.
21d. **Custo consolidado**: abrir o painel de gasto e conferir que o total bate com a soma das linhas de `ai_call` — incluindo as retentativas de página com modelo maior, que devem aparecer como linhas próprias e não substituir a original. Confirmar que as ações em modo manual entram com custo zero.
22. **Aparelhos**: percorrer aula → busca → revisão no iPad em pé, iPad deitado, celular e Windows. Confirmar que nada exige hover, que nenhum botão fica menor que a ponta do dedo, que a busca não dá zoom ao focar no Safari, e que o áudio continua tocando com a tela do iPad bloqueada.

No teste de aparelhos, incluir o card de glossário: o termo precisa ser um alvo de toque confortável no iPad e o card tem que fechar tocando fora dele.

**Testes de integridade — os que só existem porque a IA é injetável.** Rodam offline, contra fixtures gravadas de uma aula real: **reprocessamento** (card não editado é substituído, card editado é preservado e sinalizado, chave nova insere, chave sumida vira órfão e nunca é apagada — e o total não duplica); **ciclo de vida do chunk** (corrigir uma página remove os chunks antigos e nenhum chunk sobrevive apontando para `source_version` inexistente); **matéria por intervalo** (buscar filtrando Direitos Humanos acha o art. 5º e não traz os arts. 1º–4º do mesmo arquivo); **idempotência** (mesmo resultado enviado duas vezes grava uma); **truncamento** (janela estourada corta pelo critério declarado e devolve o aviso); **teto** (chamada acima do limite é bloqueada antes de sair, não depois).

Demais testes com pytest onde erro é silencioso: claim de job sem corrida, validação do JSON Schema da IA, **detecção de sinais em código** (`signals.py`: agrupamento de repetições, queda de palavras/minuto marcando ditado) contra uma transcrição de referência, **integridade dos blocos** (todo bloco tem intervalo de tempo válido e dentro da duração do áudio), **corte de clipes** (limites dentro do áudio, sem cortar no meio de palavra), **geração de cloze** (não apaga a frase inteira nem palavra irrelevante), **agendamento com confiança** (o campo não distorce o SM-2), **parser da ponte manual** (bloco JSON cercado de conversa, JSON puro, resposta truncada, resposta inválida → recusa em vez de gravar lixo), **fonte de contexto** (`window.py`: toda ação pós-processamento monta o prompt a partir do recorte **literal** da transcrição no intervalo do tópico — nunca a partir da aula editada, nunca a transcrição inteira; o recorte não corta explicação pela metade), **sinalização de baixa confiança** (citação e latim abaixo do limiar são marcados; confirmação não reaparece; correção se propaga para citações e cards), **casamento de termos do glossário** (fronteira de palavra, acento, plural, primeira-ocorrência-por-bloco, e nunca marcar dentro de tag HTML), **deduplicação de termo** (definição nova de grafia existente anexa ao termo em vez de criar outro), **ordenação das definições** no card, **fusão de termos** (definições e variantes migram, nada órfão), extração de citações (`art. 1.238`, `§ 2º`, `inciso III`, `CF/88`, `Súmula 331`), **resolução do diploma padrão** (`art. 121` em TGC → `CP:121`; em TGDC → `CC:121`), ranking da busca com acentuação, conversão HTML→Markdown, vinculação doc↔aula por data, e agendamento SM-2.

---

## Decisões fechadas — não reabrir

Cada uma destas foi discutida e decidida. Estão aqui com o motivo para que uma sessão futura não proponha de novo a alternativa já descartada.

| Decisão | Por quê |
|---|---|
| **Worker local, não clone com banco sincronizado** | Dois bancos editáveis exigem sync bidirecional e resolução de conflito — a parte mais cara e bugada de construir. A VPS é fonte única; o mesmo repositório roda com `ROLE=worker` na máquina local só para usar a GPU |
| **Áudio original apagado da VPS após transcrever** | Fica um mp3 32kbps (~30MB/aula) para ouvir de qualquer lugar; o original vai para `archive/` no PC. ~30MB em vez de ~120MB por aula |
| **Fonte de contexto = transcrição literal recortada por tópico** | Paráfrase em texto jurídico distorce silenciosamente ("poderá"×"deverá", "nulo"×"anulável"). A aula editada é índice e leitura, nunca fonte. Recorte de 2–5k tokens mantém fidelidade, custo baixo e a ponte manual viável |
| **Processamento inicial em uma chamada só** | Dividir em duas sai mais caro: paga-se a aula editada duas vezes, como saída e como entrada ($0,475 × $0,435) |
| **Busca indexa a transcrição bruta, não a aula editada** | Indexar as duas daria dois resultados para a mesma fala. Os timestamps dos blocos ligam um acerto ao trecho editado correspondente |
| **Google Docs: link para escrever, sync só para indexar** | O app nunca escreve no Docs. O editor oficial é melhor que qualquer um que eu construísse, e direção única elimina conflito de edição |
| **Criar doc por link de cópia de modelo, não pela API** | Service account não tem cota de armazenamento e o Google recusa criação em conta pessoal (`Service Accounts do not have storage quota`). Só funcionaria em Shared Drive do Workspace |
| **Glossário: um termo, várias definições** | Mesmo termo tem sentidos diferentes por matéria e é refinado ao longo do semestre. O card mostra todas com procedência; quem julga é você. Sem "definição canônica" |
| **Marcação de glossário em tempo de renderização** | Texto fica limpo no banco. Corrigir uma variante conserta todo o conteúdo passado na hora, sem reprocessar nada |
| **ASR curto (Feynman) na CPU da VPS, não na GPU** | Se dependesse da GPU, a feature morreria toda vez que você estudasse com o PC desligado. 60s de áudio saem em segundos com `small`, e a IA compara sentido, não palavra |
| **Foto e PDF escaneado vão para modelo de visão, não para OCR tradicional** | Tesseract precisaria de tratamento de imagem (endireitar, corrigir perspectiva, binarizar) e ainda erraria em português acentuado e página curva. Visão entende estrutura de página. Escalar é por página, não por capítulo |
| **Transcrição por visão via Claude Code, não API de visão da Anthropic** | Mesma decisão do resto do app ("nunca `ANTHROPIC_API_KEY`"), estendida pra fase 10: o Read tool já lê imagem nativamente, então não há motivo pra abrir exceção só porque o plano original citava `claude-haiku-4-5`. `library/vision.py` (o stub injetável) foi removido; a skill `transcrever-paginas` ocupa o lugar que a API ocuparia, mesmo padrão do `processar-aula` |
| **PDF escaneado decide página a página, não o arquivo inteiro** | Um PDF pode ter capítulos digitados e um anexo escaneado no mesmo arquivo. Tratar o arquivo inteiro como "nativo" perderia texto de páginas sem camada; tratar tudo como "escaneado" gastaria transcrição por visão em página que já tem texto de graça |
| **Página fotografada não passa por portão de aprovação antes de "elegível"** | Diferente de áudio (Whisper transcreve sozinho, sem curadoria — daí `Transcript.aprovado_em`), a foto só existe porque você já escolheu e tirou ela — a curadoria da fonte já aconteceu no upload. `MaterialPage.status="pendente"` significa só "ainda não transcrita" |
| **Mapa de cobertura é sempre recalculado, nunca guardado** | Materiais entram e saem (sobreposição pode substituir uma porção por outra); guardar "o que falta" como estado exigiria manter sincronizado a cada mudança. Comparar `WorkSection` contra os materiais na hora (`library/coverage.py`) é barato e nunca fica desatualizado |
| **Tipo de material é tabela, não enum** | Você disse que vai expandir os tipos ao longo do semestre. Enum exigiria migração a cada tipo novo; tabela + tags livres absorve o que vier |
| **Citação carrega a página da obra, não a do PDF** | Capítulo escaneado começa na p. 1 do arquivo e na p. 247 do livro. Sem o deslocamento, toda citação de trabalho sai errada — e errada de um jeito que não se percebe |
| **Glossário único do curso, não por matéria** | Termo jurídico atravessa disciplinas — "boa-fé" e "prescrição" valem em Civil, Penal e Processual. Um verbete definido em TGDC continua marcando textos de Penal dois anos depois. É o artefato mais duradouro do sistema |
| **A ordem das definições sai do teor do texto, e errar não custa** | O card mostra todas de qualquer jeito, então a ordenação é conveniência, não correção — o que permite heurística simples (matéria do documento + proximidade de vocabulário + recência) sem risco de esconder a definição certa |
| **`deriv_key` em todo artefato derivado** | Sem identidade estável, reprocessar só pode apagar tudo (perde suas edições) ou inserir tudo (duplica a fila). O diff por chave é o que torna a promessa de "preserva o que você editou" implementável |
| **Reindexar é apagar e regravar, nunca atualizar** | O índice é derivado. Sem regra de morte, corrigir um número de artigo deixa o valor errado na busca — e você o cita num trabalho com a referência ABNT correta em volta |
| **`chunk` sem `subject_id`** | Matéria é atributo da relação trecho↔uso, não do trecho. Um livro serve quatro matérias em faixas diferentes; qualquer valor único no chunk quebra o filtro de busca |
| **Assunto global com cobertura datada** | Terceira aplicação do mesmo padrão já usado em obra/uso e termo/definição. "Prescrição" é um assunto só do curso; cada matéria registra que o cobriu. É o que faz Civil I e Civil III se encontrarem em vez de cada semestre recomeçar do zero |
| **Assuntos emergem das aulas; ementa é opcional** | Depender de cadastro manual da ementa significaria, na prática, nunca ter agrupamento acima da aula — e sem ele não há escopo de prova nem plano regressivo. Vem como campo a mais na chamada de IA que já existe, sem custo novo. A ementa oficial enriquece, não bloqueia |
| **Assunto nasce com fundir/renomear/separar** | Proposta automática fatia demais ou de menos; sem as ferramentas de correção desde o início, viram dezenas de assuntos quase-iguais em dois meses — o mesmo apodrecimento que a fusão evita no glossário |
| **Questões e pares presos ao assunto, não à matéria** | Assunto é global, então a dissertativa escrita em Civil I reaparece em Civil III e na preparação para a OAB, em vez de morrer com o semestre |
| **Card de discriminação é `CardProposal` com `tipo`, não tabela nova** | Mesmo padrão de "sem duplicar linha, sem outra tabela" já usado no próprio `CardProposal` (proposta→ativo). Uma tabela separada exigiria duplicar SM-2, fila diária, calibração e modo prova, que já existem prontos e são genéricos sobre `CardProposal` |
| **Timestamps do par confundível são opcionais no schema, não exigidos** | O par cobre dois momentos da aula, não um intervalo só, e às vezes a IA não consegue isolar onde cada termo foi explicado. Preferir null a inventar um horário — o card de discriminação funciona sem áudio, só perde o botão de ouvir daquele lado |
| **Chave de dedup do par é a identidade dos dois termos, não o intervalo de origem** | Diferente de bloco/card/artigo (cuja chave hasheia o texto da transcrição no intervalo), o par não tem um intervalo único — termo_a e termo_b canonizados em ordem alfabética são o que garante que "A × B" e "B × A" de duas passadas caiam na mesma linha |
| **Semestres encadeados, não isolados** | Direito é cumulativo: glossário e cards de TGDC continuam valendo em Civil II. Tratar cada semestre como ilha destruiria o acumulado justo quando ele começa a render |
| **Reprocessar preserva tudo que você editou** | Melhorar o prompt não pode custar o trabalho manual acumulado. Só a geração automática intocada é substituída, com resumo prévio do que muda |
| **Fila com teto diário e modo recuperação** | Fila que explode após uma ausência é a causa clássica de abandono de revisão espaçada. Atrasar o cronograma é aceitável; quebrar o hábito, não |
| **Obra é permanente e sem matéria; quem tem matéria e semestre é o uso** | O mesmo livro serve seis semestres e várias disciplinas. Prender a obra a uma matéria obrigaria a duplicá-la a cada reaproveitamento e quebraria o histórico |
| **O uso carrega intervalo, não o arquivo inteiro** | A Constituição atende quatro disciplinas em faixas diferentes do mesmo volume. Vínculo no arquivo inteiro geraria material fora do escopo; vínculo por faixa dá alvo preciso à geração de cards |
| **Depois de transcrita, a imagem não volta para a IA** | A leitura já foi feita uma vez com qualidade. Reenviar fotos em cada chamada seria caro, lento e sem ganho — e ao contrário da aula editada, a transcrição por visão é literal, então não há risco de paráfrase. A imagem fica como âncora de conferência |
| **Ordem das porções sai do intervalo de páginas, não de arrastar** | Ordenação manual precisa ser refeita a cada adição e apodrece ao longo de anos. Intervalo de páginas se ordena sozinho e continua correto para sempre; arrastar fica só para porções sem numeração conhecida |
| **Transcrição de livro sai por download e área de transferência, não por arquivo no Drive** | Criar arquivo no Drive automaticamente exigiria OAuth com a conta pessoal, publicar o app e manter token vivo — a service account não tem cota e o Google recusa. Baixar não usa credencial nenhuma, e como nada nasce na pasta sincronizada, não há risco de a transcrição voltar como material duplicado |
| **Dados da obra vêm da ficha catalográfica, por foto** | É a fonte normalizada pela própria biblioteca, mais confiável que a capa, e o pipeline de visão já existe. Cadastrar livro vira uma foto em vez de um formulário |
| **Campo de referência manual sobrepõe a ABNT automática** | Organizador, tradutor, e-book, volume de série e capítulo em coletânea são casos em que a montagem automática erra. Escrever uma vez à mão resolve todas as citações daquela obra |
| **Backup só do banco; mídia é reconstruída** | Os mp3 são deriváveis dos originais arquivados no seu PC, então guardá-los duplicaria gigabytes sem ganho. Backup diário de poucos MB, e uma ação *reconstruir mídia* refaz o resto |
| **Restauração com cópia de segurança prévia e comparação** | É a única operação que apaga dados de propósito. O erro provável não é restaurar — é restaurar o backup errado, e isso precisa ser visível antes e reversível depois |
| **Vários workers, sem fallback automático** | Desktop e notebook competem pela mesma fila (o claim atômico já garante). Fallback silencioso para CPU produziria transcrição pior sem você saber; o botão *transcrever na VPS agora* é acionado por você, quando o custo da espera compensa a perda de qualidade |
| **Agrupamento de áudios marcado no upload, não inferido por horário** | Grade horária adivinhando matéria é complexidade que erra em semana atípica (aula trocada, reposição, feriado). Marcar no momento do upload é explícito e você ainda lembra qual arquivo é qual |
| **Convite de acesso adiado para o v3** | Cookies, códigos, painel e polling construídos antes de o app fazer algo útil. Token único cobre seus aparelhos hoje |
| **Ementa e provas antes do fim** | O plano regressivo depende delas, e é ele que dá motivo de abrir o app todo dia |
| **Google Doc é um `material`, não uma entidade própria** | Dois modelos para "texto que não é aula" era duplicação. Unificado, some uma tabela, uma tabela de vínculo e um campo de chunk — e o doc ganha uso em **várias matérias**, que preso a um `subject_id` ele não teria. Custava zero fazer antes de existir código; depois custaria migração |
| **Vinculação doc↔aula é auto-commit quando confiante, não proposta pra aprovar** | Diferente de card/termo/assunto (sempre "propostos"), um material com pasta reconhecida vira `MaterialUse` direto — é só um vínculo de índice/busca, reversível com um clique, sem o peso de entrar numa fila de revisão. "Sem certeza" (pasta não reconhecida) é o único caso que exige toque em "Não vinculados" |
| **Comparação de `gdoc_modified_time` ignora timezone** | `DateTime(timezone=True)` no SQLite não guarda o offset — reler do banco sempre volta naive. Comparar direto contra o `modifiedTime` (aware) da API do Drive dava sempre falso e quebrava a sync incremental (reprocessava tudo, toda vez). A API do Drive só devolve UTC, então descartar o tzinfo dos dois lados antes de comparar é seguro |
| **Busca unificada é quatro tabelas FTS5 dedicadas, não uma `chunk_fts` só** | A fase 12 tentou literalmente o `chunk_fts` único que este plano descrevia, mas FTS5 de conteúdo externo (`content=`) só aceita UMA tabela-fonte por índice — um `chunk_fts` de verdade exigiria uma tabela `chunk` intermediária duplicando texto de `material`/`material_page`/`edited_block`/`definition`, com sincronização própria. Em vez disso, mesmo padrão de `transcript_fts` (fase 5) repetido: uma FTS5 por fonte, resultados combinados por `bm25` em Python na rota de busca — mesma experiência unificada pro usuário, sem tabela extra pra manter sincronizada |
| **Uma tabela `ai_call` para todo custo de IA** | Custo estava em três campos espalhados, sem visão do total. Unificado, o painel de gasto e o teto mensal passam a ser possíveis, retentativas viram linhas em vez de sobrescrever, e vira o log de depuração das chamadas |
| **Quatro entregas utilizáveis, não um v1 único** | A ordem anterior tinha dependências quebradas (glossário marcando livros que só existiam sete fases depois) e um bloco de catorze fases contradizia o risco declarado no topo deste plano. Mesmo escopo, ordem consertada, e a entrega A já é útil sozinha |
| **Fila de revisão intercala matérias por padrão** | Intercalar retém melhor que estudar em blocos, e sai de graça da fila por vencimento. Filtro por matéria existe como exceção, não como caminho padrão |
| **Ponte manual é o caminho único de IA, não um fallback** | Decisão do usuário: nunca usar `ANTHROPIC_API_KEY` no dia a dia. Um chat do Claude Code faz manualmente (RUNBOOK.md + `.claude/skills/processar-aula/`) o que a API faria — custo zero, ocupa a assinatura em vez da API metered. Toda passada de IA sempre por Opus explícito na chamada do Agent tool, nunca herdando o modelo do chat corrente (Sonnet, Haiku etc.), porque não há como fixar modelo no frontmatter de um skill |
| **`condition_on_previous_text=False` no transcritor** | O padrão do faster-whisper é `True`; numa aula de ~2h isso deixa o modelo se condicionar no que ele mesmo gerou, compondo erro sobre erro num loop de repetição/alucinação. Confirmado com um caso real: uma frase inteira sumiu da transcrição de ~111min mas saiu perfeita ao re-transcrever o mesmo trecho isolado, sem contexto acumulado |
| **Aprovar a transcrição trava edição E retranscrição, não só retranscrição** | Cogitado deixar só a retranscrição bloqueada (edição continuaria liberada); usuário pediu trava completa nas duas. Só "reabrir revisão" libera de novo — de propósito um passo separado, não algo que outro botão faz de lambuja |
| **Guia de aula é artefato separado da aula editada, não substituto** | O guia permite reordenar raciocínio dentro de uma seção (conceito → explicação → exemplo), o que quebraria a garantia de bloco = intervalo tocável que a aula editada carrega. Por isso vivem em campos diferentes (`Lesson.guia_md` vs `EditedBlock`), com persistência e reconcile próprios — mas **artefato separado não implica chamada separada** (ver linha abaixo) |
| **Guia de aula sai da mesma leitura da aula editada, não de uma segunda chamada** | Ler a transcrição inteira duas vezes (uma pra aula editada/cards, outra pra guia) pra gerar dois artefatos da mesma fonte era desperdício puro — na ponte manual isso significava um agente processando ~27k tokens de novo do zero só pra reformatar. `guia_md` virou campo de `LessonProcessingOutput`; `ai/guia.py` (prompt/pacote/parser próprios) foi removido. O reconcile/persistência dos dois artefatos continua tão separado quanto antes — só a chamada que virou uma |
| **Matéria "LIXO" para dado de teste/descartável** | Antes disso, testar em produção local sujava matérias reais (TGDC etc.) e exigia limpeza manual depois de cada teste. Uma matéria dedicada absorve isso; nunca entra nas etapas de transcrever/processar do RUNBOOK.md (filtrada explicitamente) |
| **ASR curto do Feynman é sempre automático, a única passada de IA do app sem ponte manual** | Transcrever com `faster-whisper` não é uma chamada paga da Anthropic — é o mesmo modelo local que já roda de graça na válvula de emergência da fase 4, só que pequeno. A regra "nunca API paga" é sobre `ANTHROPIC_API_KEY`, não sobre IA em geral; só a AVALIAÇÃO da explicação (uma chamada de verdade pra Anthropic) segue a ponte manual |
| **Rede de conceitos é script, não IA** | Pedir pra IA comparar cada termo contra o glossário inteiro pra propor conexão tem custo O(n²) que cresce sem controle conforme o glossário cresce. Coocorrência textual (`glossary/matcher.py::find_matches` rodado sobre `EditedBlock.texto`) e cards de discriminação já existentes (fase 8b) cobrem o mesmo problema a custo zero/quase-zero, sem IA nova. Ver seção "5b. Rede de conceitos" |
| **Rede de conceitos é contextual, sem página/rota própria** | Cogitado uma página `/rede` isolada com seletor de escopo; o uso real é sempre "quero ver a rede desta matéria" ou "desta aula", nunca a rede solta sem contexto. Embutida em `subject_detail.html` (nível matéria) e `lesson_detail.html` (nível aula, com toggle pro nível bloco na mesma tela) — decisão do usuário |

## Continuar em uma sessão nova

A fase 0 já rodou faz tempo: `PLANO.md` e `CLAUDE.md` já existem na raiz do repo e são lidos automaticamente por qualquer chat aberto na pasta do projeto — **não precisa mais apontar caminho nenhum**, só pedir a próxima fase.

**Prompt pra abrir o chat novo:**

> `Leia o PLANO.md (e o RUNBOOK.md) e execute a fase 16.`

Isso basta porque CLAUDE.md já instrui o chat a ler os dois antes de mexer em qualquer coisa. A **entrega B está fechada** (fases 6–8b), a **fase 9 (materiais e Google Docs) também**, a **fase 10 (Biblioteca) também**, a **fase 11 (Glossário) também**, a **fase 12 (busca unificada e página do assunto) também**, a **fase 13 (produção — Feynman e dissertativa) também**, e a **fase 14 (provas, plano regressivo e exportação) também** — ver o bloco "Status" dentro de cada fase, acima. A **fase 15 (mapa e destaques em áudio) fecha a Entrega D — o v1 inteiro (fases 0–15) está pronto.** A próxima é a fase 16 (artigos e legislação), primeira do v2, fora do escopo original combinado — vale confirmar com o usuário antes de começar.

**Antes de rodar a fase 9 de verdade** (ela está codificada e testada com fixtures, mas nunca tocou a API real do Google): siga "Google Docs" no PLANO.md pra criar o projeto no Google Cloud, ativar Drive+Docs API, gerar a service account, compartilhar a pasta "Faculdade" com o e-mail dela, e preencher `GOOGLE_SERVICE_ACCOUNT_JSON` + `GOOGLE_DRIVE_FOLDER_ID` no `.env`. Depois, em cada matéria (`/subjects/{id}`), preencha `drive_folder_id` (a pasta daquela matéria dentro da "Faculdade") e `doc_modelo_id` (o Google Doc que "Criar doc desta aula" copia) se quiser os dois recursos.

Dois avisos que só existem porque já foram aprendidos na prática, não estavam no plano original:

- **Nunca use a API paga — nem pra texto, nem pra visão.** O usuário decidiu que toda passada de IA é feita manualmente, por um chat do Claude Code seguindo o RUNBOOK.md — não `ANTHROPIC_API_KEY`. Isso vale pro processamento de aula (fase 6) **e** pra transcrição de página de livro por foto (fase 10, que originalmente previa `claude-haiku-4-5` via API e acabou usando o Read tool do Claude Code em vez disso). Antes de processar qualquer aula/material com IA, leia o RUNBOOK.md inteiro; ele tem o passo a passo e uma armadilha de encoding real e testada (texto acentuado como argumento inline de curl corrompe silenciosamente).
- **Sempre Opus para processamento de IA**, mesmo que o chat esteja rodando outro modelo — dispare via Agent tool com `model: "opus"` explícito, nunca herdando o modelo da sessão. Vale também pros atalhos automatizados (`processar-aulas.ps1`, `transcrever-paginas.ps1`), que já chamam `claude -p --model opus` explícito.

Vale ir por fases, conferindo cada uma antes da seguinte. **A entrega A inteira (fases 0–5) não depende de nada externo além do DNS** e já está pronta; a **entrega B (fases 6–8b) também está pronta**; a **fase 9 está pronta em código**, mas depende da service account (acima) pra sync de verdade funcionar — sem ela, cadastro manual de material (pdf/foto/texto/link) e "Criar doc desta aula" já funcionam hoje; a **fase 10 (Biblioteca) está pronta e testada contra o staging real** (upload de PDF/foto, extração nativa, transcrição por visão via skill, referência ABNT, mapa de cobertura, aviso de sobreposição); a **fase 11 (Glossário) está pronta e testada contra o staging real** (proposta pela IA, aceitar/fundir/separar/variantes, destaque em tempo de renderização na aula editada e na leitura de obra); a **fase 12 (busca unificada e página do assunto) está pronta e testada contra o staging real** (cinco fontes combinadas por relevância, filtro por tipo/matéria/período, termo fixado no topo, e a página do assunto com termos/artigos/material derivados das aulas vinculadas). **A Entrega C está fechada.** A **fase 13 (Feynman e dissertativa) também está pronta e testada contra o staging real** (gravação e ASR curto automático, avaliação e correção pela ponte manual, histórico de tentativas). A **fase 14 (provas, plano regressivo e exportação) também está pronta e testada contra o staging real** (ementa opcional que enriquece sem substituir, painel do plano regressivo calculado na hora, PDF de aula editada e de apanhado de prova, bibliografia ABNT e exportação do corpus inteiro em .zip). A **fase 15 (mapa e destaques em áudio) também está pronta e testada** (mapa Mermaid autohospedado com nós ligados ao glossário, fila de clipes cortados sob demanda do mp3 com Media Session). **O v1 inteiro (fases 0–15, entregas A–D) está pronto.**

---

## Pontos a confirmar antes de começar

- Apontar `drwyver.mecadosjogos.app.br` (registro A) para o IP da VPS antes do deploy — o Traefik (compartilhado com outros projetos na mesma VPS, ver README.md) só emite o certificado depois que o DNS resolve.
- Disco livre na VPS — a ~30MB por aula, 5 matérias por um semestre ficam em 3-5GB.
- Chave da API Anthropic (`ANTHROPIC_API_KEY`) e se você quer começar em `opus-5` ou `sonnet-5`.
- Datas das próximas provas. A **ementa deixou de ser pré-requisito** — os assuntos emergem das aulas e a ementa oficial só enriquece; se você tiver os PDFs do plano de ensino, dá para importar depois, sem pressa.
- Como sua pasta do Drive está organizada hoje — define a regra de vinculação automática na fase 9 (Entrega C).
- Nada disso bloqueia a **entrega A**: só o DNS é necessário para começar.
