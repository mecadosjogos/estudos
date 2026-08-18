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
