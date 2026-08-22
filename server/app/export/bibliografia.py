"""Bibliografia em ABNT das obras usadas numa matéria (PLANO.md, fase 14:
"para colar no trabalho ou no TCC"). Reaproveita `library/abnt.py`
inteiro -- nada novo aqui além de achar as obras e ordenar."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..library.abnt import build_reference
from ..models import Material, MaterialUse, Work


def works_used_in_subject(session: Session, subject_id: int) -> list[Work]:
    work_ids = session.scalars(
        select(Material.work_id)
        .join(MaterialUse, MaterialUse.material_id == Material.id)
        .where(MaterialUse.subject_id == subject_id, Material.work_id.is_not(None))
        .distinct()
    ).all()
    if not work_ids:
        return []
    works = session.scalars(select(Work).where(Work.id.in_(work_ids))).all()
    return sorted(works, key=lambda w: (w.autores or w.titulo).lower())


def build_bibliografia_txt(session: Session, subject_id: int) -> str:
    works = works_used_in_subject(session, subject_id)
    if not works:
        return "Nenhuma obra vinculada a esta matéria ainda.\n"
    return "\n\n".join(build_reference(w) for w in works) + "\n"
