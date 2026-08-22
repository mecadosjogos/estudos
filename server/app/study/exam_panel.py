"""Painel do plano regressivo (PLANO.md, fase 14): "dias restantes,
cobertura, cards vencidos no escopo, ritmo necessário por dia e os
assuntos com pior desempenho" -- tudo calculado na hora a partir do que
já existe (`AssuntoCobertura`, `LessonAssunto`, `CardProposal`,
`ReviewLog`, `MaterialUse`), nada guardado à parte. Funciona igual com
ou sem ementa cadastrada -- a única diferença é se `AssuntoCobertura`
tem alguma linha `status="pendente"` (tópico da ementa ainda não dado)."""

import math
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Assunto, AssuntoCobertura, CardProposal, Exam, LessonAssunto, MaterialUse, ReviewLog


@dataclass
class AssuntoDesempenho:
    assunto_id: int
    titulo: str
    taxa_acerto: float


@dataclass
class ExamPanel:
    dias_restantes: int
    total_topicos: int
    dados: int
    estudados: int
    sem_material: int
    cards_vencidos: int
    ritmo_por_dia: int
    mais_fracos: list[AssuntoDesempenho] = field(default_factory=list)


def compute_exam_panel(session: Session, exam: Exam, hoje: date | None = None) -> ExamPanel:
    hoje = hoje or date.today()
    dias_restantes = max((exam.data - hoje).days, 0)

    scope_assunto_ids = [s.assunto_id for s in exam.escopo]
    total_topicos = len(scope_assunto_ids)
    if not scope_assunto_ids:
        return ExamPanel(dias_restantes, 0, 0, 0, 0, 0, 0, [])

    coberturas = session.scalars(
        select(AssuntoCobertura).where(
            AssuntoCobertura.assunto_id.in_(scope_assunto_ids), AssuntoCobertura.subject_id == exam.subject_id
        )
    ).all()
    dados = sum(1 for c in coberturas if c.status != "pendente")

    estudados = 0
    sem_material = 0
    cards_vencidos_ids: set[int] = set()
    mais_fracos: list[AssuntoDesempenho] = []

    for assunto_id in scope_assunto_ids:
        lesson_ids = session.scalars(
            select(LessonAssunto.lesson_id).where(
                LessonAssunto.assunto_id == assunto_id, LessonAssunto.status == "aceito"
            )
        ).all()

        tem_material = bool(lesson_ids) and session.scalar(
            select(MaterialUse.id).where(MaterialUse.lesson_id.in_(lesson_ids)).limit(1)
        )
        if not tem_material:
            sem_material += 1

        if not lesson_ids:
            continue

        cards = session.scalars(
            select(CardProposal).where(CardProposal.lesson_id.in_(lesson_ids), CardProposal.status == "aceito")
        ).all()
        card_ids = [c.id for c in cards]
        for c in cards:
            if c.due_date is not None and c.due_date <= hoje:
                cards_vencidos_ids.add(c.id)

        if not card_ids:
            continue
        logs = session.scalars(select(ReviewLog).where(ReviewLog.card_id.in_(card_ids))).all()
        if not logs:
            continue
        estudados += 1
        acertos = sum(1 for log in logs if log.acertou)
        taxa = acertos / len(logs)
        assunto = session.get(Assunto, assunto_id)
        mais_fracos.append(AssuntoDesempenho(assunto_id, assunto.titulo, taxa))

    mais_fracos.sort(key=lambda a: a.taxa_acerto)
    ritmo_por_dia = math.ceil(len(cards_vencidos_ids) / dias_restantes) if dias_restantes > 0 else len(cards_vencidos_ids)

    return ExamPanel(
        dias_restantes=dias_restantes,
        total_topicos=total_topicos,
        dados=dados,
        estudados=estudados,
        sem_material=sem_material,
        cards_vencidos=len(cards_vencidos_ids),
        ritmo_por_dia=ritmo_por_dia,
        mais_fracos=mais_fracos[:3],
    )
