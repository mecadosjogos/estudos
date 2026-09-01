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
porém, você pode citá-lo ou incorporá-lo diretamente — até literalmente, se
for prioritário — sempre prefixado com "**Material da aula:**" pra quem lê
saber que aquele trecho não foi falado, veio escrito.

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
   "-", indentada por nível) só com a hierarquia de classificações que o
   professor efetivamente construiu na fala (ex.: "a lei penal se divide
   em incriminadora ou não incriminadora; a não incriminadora se divide em
   explicativa ou permissiva" vira três níveis aninhados). Nunca complete
   com uma classificação "padrão" da doutrina que não foi mencionada nesta
   aula — um ramo não subdividido pelo professor fica como folha. Uma ou
   duas palavras por nó, não frases.
3. "## Sumário dos tópicos abordados" — lista dos tópicos.
4. Corpo organizado por seções ("## <título da seção>"), cada uma podendo
   ter sub-títulos "###", "####" e assim por diante, quantos níveis o
   próprio professor efetivamente construiu (ou o material da aula, se
   for de lá que vem a profundidade) — sem limite artificial de
   profundidade, mas também sem forçar nível que não existe: um raciocínio
   de dois níveis fica em dois, um de quatro fica em quatro, nunca invente
   uma subdivisão só pra preencher hierarquia (mesma cautela da árvore de
   conhecimento acima). Só o "##" de seção é numerado pelo código — os
   sub-títulos dentro do corpo, em qualquer nível, ficam como você
   escrever, sem numeração.
   Parágrafos devem seguir a pausa/virada de assunto natural da fala, não
   amontoar tudo num bloco só de texto denso. Depois de identificar a
   hierarquia/estrutura de um raciocínio (o professor enumerando itens do
   mesmo tipo, uma classificação com subitens, uma sequência de passos),
   use a formatação que melhor transmite essa estrutura — lista para itens
   paralelos, sub-título pro nível certo de uma subdivisão de verdade
   dentro da seção, negrito para os termos que ancoram a classificação —
   em vez de aplainar tudo em prosa corrida só porque "parágrafo seguindo
   a fala" é
   a regra geral; a formatação existe pra revelar a estrutura que já está
   no raciocínio do professor, não só pra decorar o texto. Reorganizar em
   lista/subtítulo/negrito é só isso — reorganizar: as palavras e os
   termos técnicos continuam sendo os mesmos que o professor usou, nunca
   resumidos ou reformulados pra caber no formato. Isso importa de
   verdade — é comum o professor avisar que a prova cobra exatamente o
   que foi dito em aula, com os termos que ele usou. Quando o
   professor apresentar um exemplo ou caso prático, identifique com
   "Exemplo:" no início do trecho, mesmo padrão do "Aluno:"/"Pergunta de
   aluno:" (ver regra geral acima); quando for um erro comum, pegadinha
   ou autocorreção do professor (mesmo critério do tipo de bloco
   `atencao`), identifique com "Atenção:" do mesmo jeito. Use negrito nos
   mesmos pontos que os
   sinais calculados em código (repetição/ritmo, ver acima) já usaram pra
   marcar um bloco como `destaque-prova` — não redetecte isso do zero,
   reaproveite a mesma leitura pra manter o guia consistente com a aula
   editada sobre o que é central.
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
