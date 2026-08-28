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

Os "sinais calculados em código" abaixo (repetição e ritmo) já foram
detectados automaticamente — use-os para calibrar destaque (uma ideia
repetida três vezes é candidata a "destaque-prova"; um trecho de ritmo muito
lento é candidato a "ditado"), não repita esse trabalho.

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

GUIA DE AULA (campos guia_titulo/guia_arvore/guia_secoes/guia_topicos/
guia_trechos_incompletos): além dos blocos tipados acima, produza também
um guia de leitura estruturado — um artefato diferente, não uma cópia dos
blocos, com uma liberdade que os blocos de `aula_editada` NÃO têm: dentro
de uma seção, você pode REORDENAR o raciocínio (conceito → explicação →
exemplo → observações) desde que seja só reorganização do que já foi
dito, nunca reescrita de conteúdo — os blocos de `aula_editada` continuam
presos à ordem/tempo originais, porque ▸ ouvir o original depende disso.
As mesmas regras de fidelidade ("não invente", preserve a voz do
professor) valem aqui também; não resuma a ponto de perder conteúdo — o
objetivo é organizar, não encurtar.

- guia_titulo: título da aula, se identificável, senão "Aula sem título
  identificado".
- guia_arvore: a árvore (na verdade pode ser uma FLORESTA — vários ramos
  independentes, sem raiz única forçada) de classificações que o
  professor efetivamente construiu na fala (ex.: "a lei penal se divide
  em incriminadora ou não incriminadora; a não incriminadora se divide em
  explicativa ou permissiva" vira três níveis aninhados). Nunca complete
  com uma classificação "padrão" da doutrina que não foi mencionada nesta
  aula — um ramo não subdividido pelo professor fica como folha (lista de
  filhos vazia). Uma ou duas palavras por nó, não frases. Se o professor
  não construiu classificação nenhuma nesta aula, devolva lista vazia.
- guia_secoes: o corpo do guia, organizado por seções, nesta ordem.
  Quando um aluno ou outra pessoa fala, identifique com "Aluno:" ou
  "Pergunta de aluno:" dentro do texto da seção, separado da fala do
  professor — só inclua quando relevante pro raciocínio que vem em
  seguida. Use negrito nos pontos que o próprio professor tratou como
  centrais (ênfase na fala, repetição, "isso cai em prova", "atenção",
  "gravem isso").
- guia_topicos: o sumário — um item por seção de guia_secoes, na MESMA
  ordem (a ligação entre sumário e seção é a posição na lista, calculada
  em código depois — não é um campo que você preenche). Só o título de
  cada tópico.
- guia_trechos_incompletos: se houver, a lista dos trechos marcados como
  "[trecho incompleto/inaudível na transcrição]" dentro de guia_secoes.

IMPORTANTE: nunca digite números nesses campos (nem "1.", nem "Seção 2",
nem nada equivalente) — a numeração do sumário e das seções sempre é
calculada pelo código a partir da posição na lista, nunca por você. Isso
evita sumário e seções saírem com numeração inconsistente entre si.

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

    return f"""{INSTRUCTIONS}

MATÉRIA: {lesson.subject.nome} ({lesson.subject.sigla})
DIPLOMA PADRÃO: {lesson.subject.diploma_padrao or "não definido"}
AULA: {lesson.titulo} — {lesson.data.isoformat()}

SINAIS CALCULADOS EM CÓDIGO:
{signals_json}

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
