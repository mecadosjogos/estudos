"""Exporta a transcrição bruta de uma aula (texto puro, sem timestamps)
para stdout -- reusável sempre que precisar do .txt, sem escrever o
comando do zero toda vez.

Uso (de dentro do container, onde o banco de verdade mora):

    docker compose exec server python scripts/export_transcript.py <lesson_id> > transcricao.txt

Ache o id da aula em /lessons/{id} no navegador, ou listando aulas:

    docker compose exec server python -c "
from sqlalchemy import select
from app.db import holder
from app.models import Lesson
with holder.SessionLocal() as session:
    for l in session.scalars(select(Lesson)).all():
        print(l.id, l.titulo)
"
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db import holder  # noqa: E402
from app.models import Transcript  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        print("uso: python scripts/export_transcript.py <lesson_id>", file=sys.stderr)
        raise SystemExit(1)

    try:
        lesson_id = int(sys.argv[1])
    except ValueError:
        print(f"lesson_id precisa ser um número, recebi {sys.argv[1]!r}", file=sys.stderr)
        raise SystemExit(1)

    with holder.SessionLocal() as session:
        transcript = session.scalar(select(Transcript).where(Transcript.lesson_id == lesson_id))
        if transcript is None:
            print(f"aula {lesson_id} não tem transcrição ainda", file=sys.stderr)
            raise SystemExit(1)
        print(transcript.full_text)


if __name__ == "__main__":
    main()
