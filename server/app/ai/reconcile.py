"""Diff de reprocessamento por deriv_key (PLANO.md, Integridade #1):

| Situação                     | Ação                                    |
|-------------------------------|------------------------------------------|
| Mesma chave, não editado      | Substitui                                |
| Mesma chave, editado_em cheio | Preserva e sinaliza "há versão nova"     |
| Chave nova                    | Insere como proposta                     |
| Chave sumiu                   | Marca órfão — nunca apaga                |

Genérico sobre os cinco tipos de artefato derivado (EditedBlock,
CardProposal, AnnouncementProposal, OutlineItem, ArticleMention) porque
todos compartilham os mesmos quatro campos de controle.
"""

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session


def _now():
    return datetime.now(timezone.utc)


def reconcile(
    session: Session,
    model_cls,
    lesson_id: int,
    new_items: list[tuple[str, dict]],
    has_versao_nova: bool = False,
) -> None:
    """`new_items` é uma lista de (deriv_key, campos) — campos não inclui
    lesson_id nem deriv_key, só o resto (texto, start_s, etc)."""
    existing = {
        row.deriv_key: row
        for row in session.scalars(select(model_cls).where(model_cls.lesson_id == lesson_id))
    }
    seen_keys = set()

    for deriv_key, fields in new_items:
        seen_keys.add(deriv_key)
        row = existing.get(deriv_key)

        if row is None:
            session.add(model_cls(lesson_id=lesson_id, deriv_key=deriv_key, **fields))
            continue

        row.orfao_em = None
        # Nem todo modelo tem editado_em (OutlineItem é navegação pura, não
        # editável) — sem o getattr, reconciliar índice quebraria sempre.
        if getattr(row, "editado_em", None) is not None:
            # Preserva o que você editou; guarda a versão nova pra você decidir.
            if has_versao_nova:
                row.versao_nova_json = json.dumps(fields)
        else:
            for key, value in fields.items():
                setattr(row, key, value)
            if has_versao_nova:
                row.versao_nova_json = None

    for deriv_key, row in existing.items():
        if deriv_key not in seen_keys and row.orfao_em is None:
            row.orfao_em = _now()
