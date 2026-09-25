"""Espaçamento e ordem das dissertativas de UM usuário numa aula (PLANO.md,
fase 13b).

Mesma escada de caixas do "Dominar o guia" (`apply_leitner`, caixas 0..4,
caixa 5 = dominada), só que o gap é em DIAS (1, 2, 4, 7, 12) em vez de
posições na fila: dissertativa é treino de dias, não de uma sessão. A
cobertura da rubrica (parcial vale meio) faz o papel do grau de acerto --
>= 0,7 sobe, <= 0,3 volta pra caixa 0.

Ordem de "próxima questão": (1) uma tentativa sua ainda em correção ou que
falhou, pra retomar; (2) questão vencida no espaçamento; (3) questão nova
(que você nunca respondeu) do guia atual; (4) nada -- quem chama enfileira
uma geração.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DissertativaAttempt, DissertativaProgresso, DissertativaQuestion, Lesson
from .guia_scheduler import LEITNER_GAPS, apply_leitner


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _progresso(session: Session, user_id: int, question_id: int) -> DissertativaProgresso:
    progresso = session.scalar(
        select(DissertativaProgresso).where(
            DissertativaProgresso.user_id == user_id, DissertativaProgresso.question_id == question_id
        )
    )
    if progresso is None:
        progresso = DissertativaProgresso(user_id=user_id, question_id=question_id, caixa=0, streak=0)
        session.add(progresso)
    return progresso


def registrar_resultado(session: Session, user_id: int, question_id: int, cobertura: float) -> DissertativaProgresso:
    progresso = _progresso(session, user_id, question_id)
    r = apply_leitner(caixa=progresso.caixa, streak=progresso.streak, grau_acerto=cobertura, posicao_atual=0)
    progresso.caixa = r.caixa
    progresso.streak = r.streak
    progresso.ultima_cobertura = cobertura
    progresso.proxima_revisao_em = None if r.dominado else _agora() + timedelta(days=r.posicao_alvo)
    session.flush()
    return progresso


def registrar_desistencia(session: Session, user_id: int, question_id: int) -> None:
    """"Desisto, mostrar" antes de reescrever: volta pra caixa 0 e reaparece
    amanhã -- ver a resposta pronta sem ter tentado de novo não é saber."""
    progresso = _progresso(session, user_id, question_id)
    progresso.caixa = 0
    progresso.streak = 0
    progresso.proxima_revisao_em = _agora() + timedelta(days=LEITNER_GAPS[0])
    session.flush()


def tentativa_em_andamento(session: Session, user_id: int, lesson_id: int) -> DissertativaAttempt | None:
    return session.scalar(
        select(DissertativaAttempt)
        .join(DissertativaQuestion, DissertativaQuestion.id == DissertativaAttempt.question_id)
        .where(
            DissertativaAttempt.user_id == user_id,
            DissertativaQuestion.lesson_id == lesson_id,
            DissertativaAttempt.status.in_(["julgando", "redigindo", "erro"]),
        )
        .order_by(DissertativaAttempt.criado_em.desc())
        .limit(1)
    )


def questao_vencida(session: Session, user_id: int, lesson_id: int) -> tuple[DissertativaQuestion, DissertativaProgresso] | None:
    linha = session.execute(
        select(DissertativaQuestion, DissertativaProgresso)
        .join(DissertativaProgresso, DissertativaProgresso.question_id == DissertativaQuestion.id)
        .where(
            DissertativaProgresso.user_id == user_id,
            DissertativaQuestion.lesson_id == lesson_id,
            DissertativaQuestion.fonte == "guia",
            DissertativaProgresso.proxima_revisao_em.is_not(None),
            DissertativaProgresso.proxima_revisao_em <= _naive(_agora()),
        )
        .order_by(DissertativaProgresso.proxima_revisao_em)
        .limit(1)
    ).first()
    return (linha[0], linha[1]) if linha else None


def questoes_novas(
    session: Session, user_id: int, lesson: Lesson, *, excluir: set[int] | None = None
) -> list[DissertativaQuestion]:
    """Questões do guia desta aula que a pessoa nunca respondeu. Prefere as
    geradas a partir do guia atual; as de um guia antigo continuam valendo
    (a página avisa que o guia mudou), mas vêm depois."""
    respondidas = select(DissertativaAttempt.question_id).where(DissertativaAttempt.user_id == user_id)
    questoes = session.scalars(
        select(DissertativaQuestion)
        .where(
            DissertativaQuestion.lesson_id == lesson.id,
            DissertativaQuestion.fonte == "guia",
            DissertativaQuestion.id.not_in(respondidas),
        )
        .order_by(DissertativaQuestion.criado_em)
    ).all()
    excluir = excluir or set()
    atual = _naive(lesson.guia_gerado_em) if lesson.guia_gerado_em else None

    def do_guia_atual(q: DissertativaQuestion) -> bool:
        return atual is None or (q.guia_gerado_em_ref is not None and _naive(q.guia_gerado_em_ref) == atual)

    candidatas = [q for q in questoes if q.id not in excluir]
    return sorted(candidatas, key=lambda q: (not do_guia_atual(q), q.criado_em))


def dias_desde_ultima(progresso: DissertativaProgresso) -> int | None:
    if progresso.atualizado_em is None:
        return None
    return max(0, (_naive(_agora()) - _naive(progresso.atualizado_em)).days)
