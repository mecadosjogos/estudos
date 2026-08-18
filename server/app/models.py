from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

AUDIO_SEGMENT_STATUSES = ("uploading", "complete")
JOB_TARGETS = ("gpu_worker", "vps_cpu")
JOB_STATUSES = ("pending", "claimed", "done", "failed")


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

    # Posição salva do player (fase 5) — retoma de onde parou.
    posicao_s: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    audio_segments: Mapped[list["AudioSegment"]] = relationship(
        back_populates="lesson", order_by="AudioSegment.ordem", cascade="all, delete-orphan"
    )
    jobs: Mapped[list["TranscriptionJob"]] = relationship(
        back_populates="lesson", order_by="TranscriptionJob.criado_em", cascade="all, delete-orphan"
    )
    transcript: Mapped["Transcript | None"] = relationship(
        back_populates="lesson", uselist=False, cascade="all, delete-orphan"
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
    storage_path: Mapped[str] = mapped_column(String, nullable=False)  # caminho absoluto
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="uploading")

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TranscriptionJob(Base):
    """Fila de transcrição. `target` separa duas filas independentes: os workers
    de GPU só reivindicam `gpu_worker`; o botão de emergência cria e processa
    `vps_cpu` no próprio processo do servidor, sem passar pela fila HTTP.

    `claim_token` é a chave de idempotência (Limites operacionais do PLANO.md):
    o worker reenvia o resultado com o mesmo token se a resposta se perder, e o
    servidor reconhece "já recebido" em vez de duplicar a transcrição.
    """

    __tablename__ = "transcription_job"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lesson.id"), nullable=False)
    lesson: Mapped["Lesson"] = relationship(back_populates="jobs")

    target: Mapped[str] = mapped_column(String, nullable=False, default="gpu_worker")
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")

    claim_token: Mapped[str | None] = mapped_column(String, nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Transcript(Base):
    """A transcrição bruta de uma aula — nunca editada, sempre a fonte de
    verdade de trabalho (PLANO.md). Reprocessar substitui inteiramente: não há
    o que preservar aqui porque nada nela é editável pelo usuário."""

    __tablename__ = "transcript"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lesson.id"), nullable=False, unique=True)
    lesson: Mapped["Lesson"] = relationship(back_populates="transcript")

    engine: Mapped[str] = mapped_column(String, nullable=False)
    worker_name: Mapped[str] = mapped_column(String, nullable=False)
    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="transcript", order_by="TranscriptSegment.idx", cascade="all, delete-orphan"
    )


class TranscriptSegment(Base):
    """Um trecho da transcrição (a unidade natural do Whisper — frase/pausa),
    com os timestamps por palavra guardados em `words_json` em vez de uma linha
    por palavra: mantém a granularidade fina sem multiplicar milhares de linhas
    por aula de 2h."""

    __tablename__ = "transcript_segment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcript.id"), nullable=False)
    transcript: Mapped["Transcript"] = relationship(back_populates="segments")

    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    start_s: Mapped[float] = mapped_column(Float, nullable=False)
    end_s: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    words_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
