from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now():
    return datetime.now(timezone.utc)


class Subject(Base):
    __tablename__ = "subject"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nome: Mapped[str] = mapped_column(String, nullable=False)
    sigla: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    cor: Mapped[str | None] = mapped_column(String, nullable=True)
    diploma_padrao: Mapped[str | None] = mapped_column(String, nullable=True)

    # Encadeamento entre semestres (fase 2): a matéria seguinte herda glossário e cards.
    continua_de_id: Mapped[int | None] = mapped_column(ForeignKey("subject.id"), nullable=True)
    continua_de: Mapped["Subject | None"] = relationship(remote_side=[id])

    encerrada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
