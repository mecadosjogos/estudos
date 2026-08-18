"""Teto de custo mensal — checagem ANTES da chamada, nunca depois (PLANO.md,
Limites operacionais). ai_call registra depois; sem uma verificação
pré-chamada, o sistema passaria do teto e continuaria, porque nada
consultou o limite antes de gastar."""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config
from ..models import AiCall


class BudgetExceededError(Exception):
    def __init__(self, spent_usd: float, budget_usd: float):
        self.spent_usd = spent_usd
        self.budget_usd = budget_usd
        super().__init__(
            f"teto mensal de IA atingido: US$ {spent_usd:.2f} gastos de US$ {budget_usd:.2f}"
        )


def month_spend_usd(session: Session, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = session.scalar(
        select(func.coalesce(func.sum(AiCall.custo_usd), 0.0))
        .where(AiCall.criado_em >= start_of_month)
        .where(AiCall.via == "automatico")  # manual custa zero, não conta pro teto
    )
    return float(total or 0.0)


def check_budget_or_raise(session: Session) -> None:
    spent = month_spend_usd(session)
    if spent >= config.AI_MONTHLY_BUDGET_USD:
        raise BudgetExceededError(spent, config.AI_MONTHLY_BUDGET_USD)
