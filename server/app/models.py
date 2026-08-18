from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
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

    # Aula editada (fase 6) — resumo é regenerado por inteiro a cada
    # reprocessamento, nunca editado à mão, então não precisa de deriv_key.
    resumo: Mapped[str | None] = mapped_column(Text, nullable=True)

    audio_segments: Mapped[list["AudioSegment"]] = relationship(
        back_populates="lesson", order_by="AudioSegment.ordem", cascade="all, delete-orphan"
    )
    jobs: Mapped[list["TranscriptionJob"]] = relationship(
        back_populates="lesson", order_by="TranscriptionJob.criado_em", cascade="all, delete-orphan"
    )
    transcript: Mapped["Transcript | None"] = relationship(
        back_populates="lesson", uselist=False, cascade="all, delete-orphan"
    )
    blocks: Mapped[list["EditedBlock"]] = relationship(
        back_populates="lesson", order_by="EditedBlock.ordem", cascade="all, delete-orphan"
    )
    cards: Mapped[list["CardProposal"]] = relationship(
        back_populates="lesson", cascade="all, delete-orphan"
    )
    announcements: Mapped[list["AnnouncementProposal"]] = relationship(
        back_populates="lesson", cascade="all, delete-orphan"
    )
    outline_items: Mapped[list["OutlineItem"]] = relationship(
        back_populates="lesson", order_by="OutlineItem.ordem", cascade="all, delete-orphan"
    )
    article_mentions: Mapped[list["ArticleMention"]] = relationship(
        back_populates="lesson", cascade="all, delete-orphan"
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


# --- Fase 6: IA, aula editada e ponte manual ---
#
# Todo artefato derivado carrega deriv_key (Integridade #1 do PLANO.md): tipo
# + intervalo de origem + hash do conteudo-fonte. Reprocessar e um diff por
# essa chave -- substitui o que nao foi tocado, preserva e sinaliza o que foi
# editado, insere chave nova, e marca orfao (nunca apaga) o que sumiu.
# editado_em marca "voce mexeu nisso"; orfao_em marca "nao veio mais na
# ultima geracao, mas continua no banco".

BLOCK_TIPOS = ("destaque-prova", "ditado", "conceito", "exemplo", "atencao", "normal")
CARD_STATUSES = ("pendente", "aceito", "descartado")


class EditedBlock(Base):
    """Um bloco da aula editada -- a apostila que voce realmente estuda. A
    repeticao nao e apagada: vira um bloco so com repeticoes > 1 e
    origens_json guardando todos os timestamps de origem, elevando o
    destaque em vez de aparecer tres vezes."""

    __tablename__ = "edited_block"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lesson.id"), nullable=False)
    lesson: Mapped["Lesson"] = relationship(back_populates="blocks")

    deriv_key: Mapped[str] = mapped_column(String, nullable=False)
    ordem: Mapped[int] = mapped_column(Integer, nullable=False)
    tipo: Mapped[str] = mapped_column(String, nullable=False, default="normal")
    texto: Mapped[str] = mapped_column(Text, nullable=False)

    start_s: Mapped[float] = mapped_column(Float, nullable=False)
    end_s: Mapped[float] = mapped_column(Float, nullable=False)
    origens_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    repeticoes: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    baixa_confianca: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirmado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    observacao: Mapped[str | None] = mapped_column(Text, nullable=True)

    editado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    orfao_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    versao_nova_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CardProposal(Base):
    """Card de revisao proposto pela IA -- entra como pendente na tela de
    aprovacao, nunca direto na fila de revisao espacada (fase 7)."""

    __tablename__ = "card_proposal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lesson.id"), nullable=False)
    lesson: Mapped["Lesson"] = relationship(back_populates="cards")

    deriv_key: Mapped[str] = mapped_column(String, nullable=False)
    frente: Mapped[str] = mapped_column(Text, nullable=False)
    verso: Mapped[str] = mapped_column(Text, nullable=False)
    start_s: Mapped[float] = mapped_column(Float, nullable=False)
    end_s: Mapped[float] = mapped_column(Float, nullable=False)

    status: Mapped[str] = mapped_column(String, nullable=False, default="pendente")

    editado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    orfao_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    versao_nova_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AnnouncementProposal(Base):
    """Data anunciada em aula (ex.: "a prova vai ser dia 12") -- proposta
    pela IA, entra na mesma tela de aprovacao dos cards."""

    __tablename__ = "announcement_proposal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lesson.id"), nullable=False)
    lesson: Mapped["Lesson"] = relationship(back_populates="announcements")

    deriv_key: Mapped[str] = mapped_column(String, nullable=False)
    texto: Mapped[str] = mapped_column(Text, nullable=False)
    data_anunciada: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_s: Mapped[float] = mapped_column(Float, nullable=False)

    status: Mapped[str] = mapped_column(String, nullable=False, default="pendente")

    editado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    orfao_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class OutlineItem(Base):
    """Indice da aula com timestamp -- nao e editavel nem aprovavel, e
    navegacao pura, entao nao carrega status nem editado_em."""

    __tablename__ = "outline_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lesson.id"), nullable=False)
    lesson: Mapped["Lesson"] = relationship(back_populates="outline_items")

    deriv_key: Mapped[str] = mapped_column(String, nullable=False)
    ordem: Mapped[int] = mapped_column(Integer, nullable=False)
    titulo: Mapped[str] = mapped_column(String, nullable=False)
    start_s: Mapped[float] = mapped_column(Float, nullable=False)
    end_s: Mapped[float] = mapped_column(Float, nullable=False)

    orfao_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ArticleMention(Base):
    """Citacao de artigo/dispositivo dentro da aula. A normalizacao pra
    chave canonica (CC:1238 etc.) e a pagina por artigo sao v2 (fase 16) --
    aqui so guarda a mencao crua e a confianca."""

    __tablename__ = "article_mention"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lesson.id"), nullable=False)
    lesson: Mapped["Lesson"] = relationship(back_populates="article_mentions")

    deriv_key: Mapped[str] = mapped_column(String, nullable=False)
    texto_citado: Mapped[str] = mapped_column(String, nullable=False)
    start_s: Mapped[float] = mapped_column(Float, nullable=False)

    baixa_confianca: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirmado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    orfao_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AiCall(Base):
    """Log de toda chamada de IA -- automatica ou manual (custo 0). Vira o
    painel de gasto (fase 8) e a checagem de teto (antes da chamada, nunca
    depois -- Limites operacionais do PLANO.md). raw_response_json guarda a
    resposta estruturada inteira: campos que fases futuras ainda nao
    persistem (termos, pares, mapa, assuntos) nao se perdem, so esperam."""

    __tablename__ = "ai_call"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int | None] = mapped_column(ForeignKey("lesson.id"), nullable=True)

    tipo_acao: Mapped[str] = mapped_column(String, nullable=False)
    via: Mapped[str] = mapped_column(String, nullable=False, default="automatico")
    modelo: Mapped[str] = mapped_column(String, nullable=False)

    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    custo_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    raw_response_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
