"""Recorte de contexto por assunto (PLANO.md, fase 8): "toda ação
pós-processamento monta o prompt a partir do recorte literal da
transcrição... nunca a partir da aula editada". `window.py` só segue os
vínculos que `LessonAssunto` já criou — o assunto atravessa aulas porque o
vínculo atravessa aulas.

Simplificação assumida por ora: o vínculo aula<->assunto é por aula
inteira, não por intervalo dentro da aula (a IA ainda não marca onde um
assunto começa e termina numa aula) — então o recorte aqui é a
transcrição inteira de cada aula vinculada, não um trecho de 2-5k tokens.
Ainda assim nunca é a aula editada: é sempre o texto literal do Whisper.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Lesson, LessonAssunto


def build_context_for_assunto(session: Session, assunto_id: int) -> str:
    lesson_ids = session.scalars(
        select(LessonAssunto.lesson_id).where(
            LessonAssunto.assunto_id == assunto_id, LessonAssunto.status == "aceito"
        )
    ).all()
    if not lesson_ids:
        return ""

    lessons = session.scalars(
        select(Lesson).where(Lesson.id.in_(lesson_ids)).order_by(Lesson.data)
    ).all()

    parts = []
    for lesson in lessons:
        if lesson.transcript is None:
            continue
        header = f"--- AULA: {lesson.titulo} ({lesson.data.isoformat()}) ---"
        parts.append(f"{header}\n{lesson.transcript.full_text}")

    return "\n\n".join(parts)
