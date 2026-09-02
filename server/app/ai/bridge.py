"""Ponte manual (PLANO.md): os mesmos arquivos alimentam a chamada de API e
a ponte manual — o prompt é montado uma vez e ou vai para a API, ou para a
área de transferência, ou para um .md baixável. Isso mantém os dois modos
idênticos em comportamento."""

import json

from ..models import Lesson, TranscriptSegment
from .schemas import LessonProcessingOutput

INSTRUCTIONS = """Você organiza aulas de Direito em material de estudo, seguindo um formato fixo.

INSTRUÇÃO CENTRAL: reescreva sem inventar. Cada bloco da aula editada precisa
guardar o intervalo de tempo exato (start_s/end_s) do trecho de origem na
transcrição abaixo — é isso que permite ▸ ouvir o original depois. Nunca
invente número de artigo, data ou citação que não esteja na transcrição.
Não complete raciocínios que o professor deixou incompletos, não corrija o
que parecer um erro dele, e não expanda o conteúdo com conhecimento
jurídico externo à aula — mesmo que você "saiba" a resposta certa, se não
foi dito na aula, não entra.

PRESERVAÇÃO DA VOZ DO PROFESSOR: ao reescrever, mantenha ao máximo as
palavras e expressões originais. Você pode remover vício de linguagem
("né", "então assim", "tá bom") e repetição por gagueira, e ajustar
pontuação/concordância para leitura fluida — mas nunca parafraseie
conteúdo jurídico nem troque termo técnico por sinônimo. Elimine só o que
é claramente ruído de fala, nunca conteúdo.

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
mão por quem processa a aula, fonte tão primária quanto a transcrição — o
professor escreveu ou distribuiu isso na aula. Use como referência pra
calibrar importância (o que aparece aqui é forte candidato a destaque,
já que foi grifado fisicamente pelo próprio professor) e pra corrigir
grafia de termo, artigo ou citação que a transcrição trouxe errado ou
ambíguo, quando o mesmo ponto aparece escrito aqui. Diferente da
transcrição, este material NÃO tem timestamp — nunca vira bloco de
`aula_editada` nem card com start_s/end_s inventado.

Tipos de bloco (use exatamente um destes por bloco, em `tipo`):
- destaque-prova: o professor sinalizou que cai na prova, ou repetiu muito
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
▸ ouvir o original depende disso. As mesmas regras de fidelidade
("não invente", preserve a voz do professor) valem aqui também; não
resuma a ponto de perder conteúdo — o objetivo é organizar, não encurtar.

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
3. Sumário dos tópicos abordados.
4. Corpo organizado por seções/subtítulos. Quando um aluno ou outra pessoa
   fala, identifique com "Aluno:" ou "Pergunta de aluno:", separado da
   fala do professor — só inclua quando relevante pro raciocínio que vem
   em seguida. Use negrito nos pontos que o próprio professor tratou como
   centrais (ênfase na fala, repetição, "isso cai em prova", "atenção",
   "gravem isso").
5. Ao final, se houver, uma lista dos trechos marcados como
   "[trecho incompleto/inaudível na transcrição]".

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
MATERIAL DADO EM AULA (LOUSA ETC) — colado à mão, sem timestamp:
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
