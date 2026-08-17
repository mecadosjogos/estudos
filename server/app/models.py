from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

AUDIO_SEGMENT_STATUSES = ("uploading", "complete")


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


class Lesson(Base):
    __tablename__ = "lesson"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subject.id"), nullable=False)
    subject: Mapped["Subject"] = relationship()

    titulo: Mapped[str] = mapped_column(String, nullable=False)
    data: Mapped[date] = mapped_column(Date, nullable=False)

    # Sync de verdade (sincronizar conteúdo, vincular material) entra na fase 9.
    # Aqui é só o link para abrir a cópia no Google Docs.
    google_doc_url: Mapped[str | None] = mapped_column(String, nullable=True)

    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    audio_segments: Mapped[list["AudioSegment"]] = relationship(
        back_populates="lesson", order_by="AudioSegment.ordem", cascade="all, delete-orphan"
    )


class AudioSegment(Base):
    """Um arquivo de áudio subido para uma aula.

    Uma aula pode ter vários segmentos quando a gravação foi partida em dois
    (o intervalo) — `ordem` define a sequência em que o worker deve concatená-los
    antes de transcrever (fase 4). O original fica em `storage_path`, dentro de
    MEDIA_ORIGINAL_DIR, até o worker processar e a VPS apagá-lo.
    """

    __tablename__ = "audio_segment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lesson.id"), nullable=False)
    lesson: Mapped["Lesson"] = relationship(back_populates="audio_segments")

    ordem: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="uploading")

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
