"""Reordena os exercícios do "Dominar o guia" pelo índice do guia
(app/study/guia_ordem.py) -- seção por seção, tipos misturados como o
conteúdo vem, em vez da ordem em que a IA listou o lote. Não mexe no
progresso de ninguém: muda só a ordem em que o backlog entra na mesa.

Uso (de dentro do container, onde o banco de verdade mora):

    docker compose exec server python scripts/reordenar_exercicios_guia.py 35
    docker compose exec server python scripts/reordenar_exercicios_guia.py --todas

Sem acesso ao container, a mesma coisa por HTTP, aula a aula (logado):
POST /lessons/{id}/guia/exercicios-reordenar.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db import holder  # noqa: E402
from app.models import GuiaExercicio, Lesson  # noqa: E402
from app.study.guia_ordem import reordenar_exercicios  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        print("uso: python scripts/reordenar_exercicios_guia.py <lesson_id> | --todas", file=sys.stderr)
        raise SystemExit(1)

    with holder.SessionLocal() as session:
        if sys.argv[1] == "--todas":
            lesson_ids = list(session.scalars(select(GuiaExercicio.lesson_id).distinct().order_by(GuiaExercicio.lesson_id)))
        else:
            try:
                lesson_ids = [int(sys.argv[1])]
            except ValueError:
                print(f"lesson_id precisa ser um número, recebi {sys.argv[1]!r}", file=sys.stderr)
                raise SystemExit(1)

        for lesson_id in lesson_ids:
            lesson = session.get(Lesson, lesson_id)
            if lesson is None:
                print(f"aula {lesson_id} não existe", file=sys.stderr)
                raise SystemExit(1)
            ordenados = reordenar_exercicios(session, lesson)
            session.commit()
            print(f"aula {lesson_id} \"{lesson.titulo}\": {ordenados} exercícios reordenados")


if __name__ == "__main__":
    main()
