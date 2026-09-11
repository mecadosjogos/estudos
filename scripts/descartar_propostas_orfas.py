"""Descarta em lote propostas de IA órfãs (PLANO.md, Integridade #1 /
ai/reconcile.py): itens de CardProposal, AnnouncementProposal,
LessonAssunto e Definition que ainda estão "pendente"/"proposto" na tela
de aprovação mas têm `orfao_em` preenchido -- ou seja, a chave deles não
veio de volta na última passada de `processar-aula` ingerida (seja porque
foi reprocessada, seja porque o usuário reverteu pra uma resposta
anterior). `reconcile()` nunca apaga essas linhas sozinho -- só marca
`orfao_em` -- então elas se acumulam na tela de aprovação misturadas com
as propostas da passada ativa até alguém descartar uma por uma. Este
script faz esse descarte em lote, aula por aula ou pra todas de uma vez.

Roda dentro do container (mesmo padrão do `docker exec ... python -m
alembic ...` do README) porque precisa do ORM (`app.db`/`app.models`)
direto -- não existe endpoint HTTP pra isso:

    docker exec -i estudos-server-1 python scripts/descartar_propostas_orfas.py            # dry-run, todas as aulas
    docker exec -i estudos-server-1 python scripts/descartar_propostas_orfas.py --lesson-id 23
    docker exec -i estudos-server-1 python scripts/descartar_propostas_orfas.py --lesson-id 23 --confirmar

Sem `--confirmar` só lista o que seria descartado (nenhuma escrita). O
efeito é idêntico a clicar "descartar" em cada item na tela de aprovação
(`status = "descartado"`, PLANO.md/routes/ai.py) -- nunca deleta a linha.
"""

import argparse
import sys
from pathlib import Path

# Dentro da imagem (Dockerfile: COPY scripts scripts, COPY server server,
# WORKDIR final /app/server) o pacote `app` só resolve com /app/server no
# sys.path -- que não é o cwd quando este script é chamado como
# `python scripts/...` a partir de /app. Fora do container (teste local),
# server/ vive ao lado de scripts/ na raiz do repo -- mesmo cálculo.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from sqlalchemy import select  # noqa: E402

from app.db import holder  # noqa: E402
from app.models import AnnouncementProposal, CardProposal, Definition, LessonAssunto  # noqa: E402

# (modelo, campo de status, valor que marca "ainda pendente de aprovação")
TARGETS = [
    (CardProposal, "status", "pendente"),
    (AnnouncementProposal, "status", "pendente"),
    (LessonAssunto, "status", "pendente"),
    (Definition, "status", "proposto"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lesson-id", type=int, default=None, help="só esta aula (default: todas)")
    parser.add_argument("--confirmar", action="store_true", help="sem isso, só lista (dry-run)")
    args = parser.parse_args()

    session = holder.SessionLocal()
    try:
        total = 0
        for model, status_attr, pending_value in TARGETS:
            query = select(model).where(getattr(model, status_attr) == pending_value, model.orfao_em.isnot(None))
            if args.lesson_id is not None:
                query = query.where(model.lesson_id == args.lesson_id)
            orphans = session.scalars(query).all()
            if not orphans:
                continue

            by_lesson: dict[int, int] = {}
            for row in orphans:
                by_lesson[row.lesson_id] = by_lesson.get(row.lesson_id, 0) + 1

            acao = "descartando" if args.confirmar else "descartaria (dry-run)"
            print(f"[{model.__tablename__}] {acao} {len(orphans)} órfã(s): {by_lesson}")
            total += len(orphans)

            if args.confirmar:
                for row in orphans:
                    setattr(row, status_attr, "descartado")

        if args.confirmar:
            session.commit()
            print(f"pronto: {total} proposta(s) órfã(s) descartada(s).")
        else:
            print(f"dry-run: {total} proposta(s) seriam descartadas. Rode de novo com --confirmar pra aplicar.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
