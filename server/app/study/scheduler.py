"""Revisão espaçada (PLANO.md, fase 7): SM-2, fila diária intercalando
matérias, teto diário com modo recuperação, e o relatório de calibração.

SM-2 clássico: qualidade 0-5, `< 3` reinicia a sequência de acertos e volta
pra amanhã; `>= 3` avança o intervalo (1 dia -> 6 dias -> intervalo ×
fator de facilidade). Os atalhos de teclado (1-4, "Again/Hard/Good/Easy")
mapeiam pra essa escala em vez de pedir a nota crua — ninguém vai decorar
o que "qualidade 3" significa no meio do ônibus.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from itertools import zip_longest

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CONFIDENCE_LEVELS, CardProposal, Lesson, ReviewLog

QUALITY_BY_SHORTCUT = {1: 0, 2: 3, 3: 4, 4: 5}  # Again, Hard, Good, Easy


def _now():
    return datetime.now(timezone.utc)


@dataclass
class SM2Result:
    ease_factor: float
    interval_days: int
    repetitions: int
    due_date: date


def apply_sm2(
    *, ease_factor: float, interval_days: int, repetitions: int, quality: int, today: date
) -> SM2Result:
    quality = max(0, min(5, quality))

    if quality < 3:
        repetitions = 0
        interval_days = 1
    else:
        if repetitions == 0:
            interval_days = 1
        elif repetitions == 1:
            interval_days = 6
        else:
            interval_days = round(interval_days * ease_factor)
        repetitions += 1

    ease_factor = max(1.3, ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
    interval_days = max(1, interval_days)

    return SM2Result(
        ease_factor=round(ease_factor, 4),
        interval_days=interval_days,
        repetitions=repetitions,
        due_date=today + timedelta(days=interval_days),
    )


def submit_review(
    session: Session, card: CardProposal, *, confianca: str, shortcut: int, today: date | None = None
) -> ReviewLog:
    """Aplica SM-2, grava o log de calibração e atualiza o card — tudo numa
    função porque as duas coisas sempre acontecem juntas."""
    today = today or _now().date()
    quality = QUALITY_BY_SHORTCUT[shortcut]

    result = apply_sm2(
        ease_factor=card.ease_factor,
        interval_days=card.interval_days,
        repetitions=card.repetitions,
        quality=quality,
        today=today,
    )
    card.ease_factor = result.ease_factor
    card.interval_days = result.interval_days
    card.repetitions = result.repetitions
    card.due_date = result.due_date
    card.last_reviewed_at = _now()

    log = ReviewLog(card_id=card.id, confianca=confianca, qualidade=quality, acertou=quality >= 3)
    session.add(log)
    session.commit()
    return log


def _interleave_by_subject(cards: list[CardProposal]) -> list[CardProposal]:
    """Fila intercalada por padrão (PLANO.md) — retenção é melhor intercalando
    matérias do que estudando em blocos, e isso não pode virar um filtro
    'só esta matéria' escondido no meio do agendamento."""
    by_subject = defaultdict(list)
    for card in cards:
        by_subject[card.lesson.subject_id].append(card)

    result = []
    for group in zip_longest(*by_subject.values()):
        result.extend(item for item in group if item is not None)
    return result


def _redistribute_overflow(overflow: list[CardProposal], today: date) -> None:
    """O que não coube no teto de hoje não fica todo acumulado pra amanhã —
    espalha pelos próximos dias, senão a fila de amanhã já nasce estourada
    de novo (PLANO.md: 'uma semana ruim atrasa o cronograma, não quebra o
    hábito')."""
    spread_days = min(7, max(1, len(overflow) // 10 + 1))
    for i, card in enumerate(overflow):
        card.due_date = today + timedelta(days=(i % spread_days) + 1)


def build_daily_queue(
    session: Session, *, daily_cap: int, today: date | None = None
) -> tuple[list[CardProposal], bool]:
    """Devolve (fila intercalada, em_recuperacao). em_recuperacao é True
    quando o vencido excede o teto — é só informativo pra UI avisar, a
    redistribuição já aconteceu."""
    today = today or _now().date()

    due_cards = list(
        session.scalars(
            select(CardProposal).where(CardProposal.status == "aceito", CardProposal.due_date <= today)
        )
    )
    if not due_cards:
        return [], False

    # mais atrasado primeiro; empate desempata pelo que mais erra (ease_factor baixo)
    due_cards.sort(key=lambda c: (c.due_date, c.ease_factor))

    in_recovery = len(due_cards) > daily_cap
    today_cards = due_cards[:daily_cap]
    overflow = due_cards[daily_cap:]
    if overflow:
        _redistribute_overflow(overflow, today)
        session.commit()

    return _interleave_by_subject(today_cards), in_recovery


def calibration_report(session: Session) -> dict[str, dict]:
    report = {}
    for level in CONFIDENCE_LEVELS:
        logs = session.scalars(select(ReviewLog).where(ReviewLog.confianca == level)).all()
        total = len(logs)
        acertos = sum(1 for log in logs if log.acertou)
        report[level] = {
            "total": total,
            "acertos": acertos,
            "taxa_acerto": (acertos / total) if total else None,
        }
    return report


def _weakness(card: CardProposal) -> tuple[int, float]:
    logs = card.review_logs
    if not logs:
        return (0, 0.0)
    acertos = sum(1 for log in logs if log.acertou)
    return (1, acertos / len(logs))


def exam_mode_queue(session: Session, subject_id: int) -> list[CardProposal]:
    """Modo prova, versão MVP por matéria (o escopo por assunto/prova real
    é fase 8/14, quando assunto e exam existirem). Ignora agendamento,
    ordena por fraqueza: nunca revisado primeiro, depois menor taxa de
    acerto."""
    cards = session.scalars(
        select(CardProposal)
        .join(Lesson, CardProposal.lesson_id == Lesson.id)
        .where(CardProposal.status == "aceito", Lesson.subject_id == subject_id)
    ).all()
    return sorted(cards, key=_weakness)


def practice_queue(session: Session, *, exclude_ids: set[int] | None = None) -> list[CardProposal]:
    """Fila de reforço pra quando a fila do dia (build_daily_queue) já
    esvaziou e ainda dá pra continuar estudando -- ignora due_date de
    propósito (senão não sobraria nada pra mostrar) e prioriza os cards
    mais fracos. exclude_ids evita repetir na hora os cards já respondidos
    nesta mesma sessão de reforço."""
    exclude_ids = exclude_ids or set()
    cards = [c for c in session.scalars(select(CardProposal).where(CardProposal.status == "aceito")) if c.id not in exclude_ids]
    cards.sort(key=_weakness)
    return _interleave_by_subject(cards)
