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

    # Guia de aula: markdown corrido (a transcrição reorganizada por um
    # prompt simples, sem schema) -- material de leitura complementar à
    # aula editada, não um substituto dela. Regenerado por inteiro, sem
    # deriv_key, pelo mesmo motivo do resumo.
    guia_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    guia_gerado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
    assunto_proposals: Mapped[list["LessonAssunto"]] = relationship(
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
    """Card de revisão. Nasce como proposta pendente da IA (fase 6); quando
    aceito (`status="aceito"`), o mesmo registro passa a valer como card
    ativo na fila de revisão espaçada (fase 7) — sem duplicar linha, sem
    outra tabela: os campos de SM-2 só importam a partir daí."""

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

    # SM-2 (fase 7) — só passam a valer quando status="aceito".
    ease_factor: Mapped[float] = mapped_column(Float, nullable=False, default=2.5)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repetitions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    review_logs: Mapped[list["ReviewLog"]] = relationship(
        back_populates="card", order_by="ReviewLog.revisado_em", cascade="all, delete-orphan"
    )

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


# --- Fase 7: revisão espaçada, calibração e offline ---

CONFIDENCE_LEVELS = ("chutei", "acho_que_sei", "tenho_certeza")


class ReviewLog(Base):
    """Uma resposta na fila de revisão. `confianca` é marcada ANTES de
    revelar o verso (PLANO.md) — é o que alimenta o painel de calibração,
    mostrando se "tenho certeza" realmente acerta mais que "acho que sei"."""

    __tablename__ = "review_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("card_proposal.id"), nullable=False)
    card: Mapped["CardProposal"] = relationship(back_populates="review_logs")

    confianca: Mapped[str] = mapped_column(String, nullable=False)
    qualidade: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-5, escala SM-2
    acertou: Mapped[bool] = mapped_column(Boolean, nullable=False)

    revisado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# --- Fase 8: assuntos e estudo ativo ---
#
# Assunto e global (PLANO.md): "prescricao" e um so no curso inteiro, de
# Civil I a OAB. A materia so registra que cobriu, via AssuntoCobertura --
# nao existe "semestre" separado porque cada Subject ja e uma oferta de um
# semestre especifico (encadeada por continua_de, fase 2).

ASSUNTO_COBERTURA_STATUSES = ("pendente", "dado", "estudado")
ASSUNTO_ORIGENS = ("ia", "ementa", "manual")


class Assunto(Base):
    """Global, sem materia (PLANO.md: 'Assunto -- a terceira aplicacao do
    mesmo padrao'). slug e a identidade estavel usada pra deduplicar
    propostas da IA entre aulas e semestres diferentes; titulo e so
    exibicao e pode ser renomeado sem quebrar o casamento."""

    __tablename__ = "assunto"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    titulo: Mapped[str] = mapped_column(String, nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AssuntoCobertura(Base):
    """'A materia registra que cobriu o assunto' -- e aqui que mora a
    datacao (PLANO.md). Uma linha por (assunto, matéria); a matéria já
    carrega o semestre implicitamente."""

    __tablename__ = "assunto_cobertura"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assunto_id: Mapped[int] = mapped_column(ForeignKey("assunto.id"), nullable=False)
    assunto: Mapped["Assunto"] = relationship()
    subject_id: Mapped[int] = mapped_column(ForeignKey("subject.id"), nullable=False)
    subject: Mapped["Subject"] = relationship()

    status: Mapped[str] = mapped_column(String, nullable=False, default="dado")
    origem: Mapped[str] = mapped_column(String, nullable=False, default="ia")
    ordem: Mapped[int | None] = mapped_column(Integer, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LessonAssunto(Base):
    """Proposta da IA de que esta aula cobre um assunto, e depois de
    aceita, o vinculo aula<->assunto em si -- mesmo padrao do CardProposal
    (fase 6/7): uma linha so, o status decide o que ela significa agora.
    assunto_id fica nulo ate aceitar (é quando resolvemos/criamos o
    Assunto global pelo slug)."""

    __tablename__ = "lesson_assunto"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lesson.id"), nullable=False)
    lesson: Mapped["Lesson"] = relationship(back_populates="assunto_proposals")

    deriv_key: Mapped[str] = mapped_column(String, nullable=False)
    texto_proposto: Mapped[str] = mapped_column(String, nullable=False)

    assunto_id: Mapped[int | None] = mapped_column(ForeignKey("assunto.id"), nullable=True)
    assunto: Mapped["Assunto | None"] = relationship()

    status: Mapped[str] = mapped_column(String, nullable=False, default="pendente")
    orfao_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
