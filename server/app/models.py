from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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

    # Sync do Drive (fase 9): pasta desta matéria dentro da raiz compartilhada
    # com a service account -- é o sinal de maior confiança do matcher (`por
    # pasta`, PLANO.md). doc_modelo_id é o Google Doc copiado pelo botão
    # "Criar doc desta aula" (link de cópia, nunca criação pela API -- ver
    # Decisões fechadas).
    drive_folder_id: Mapped[str | None] = mapped_column(String, nullable=True)
    doc_modelo_id: Mapped[str | None] = mapped_column(String, nullable=True)

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

    # Mapa de taxonomia (fase 15) -- vem do mesmo campo `mapa_mermaid` de
    # LessonProcessingOutput desde a fase 6, só guardado cru em
    # AiCall.raw_response_json até agora. Regenerado por inteiro, sem
    # deriv_key, mesmo motivo do resumo/guia.
    mapa_mermaid: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Guia estruturado: título próprio (pode ser mais descritivo que
    # Lesson.titulo) e a árvore de conhecimento como JSON (lista de
    # {rotulo, filhos} -- ver GuiaArvoreNoOut). Regenerados por inteiro a
    # cada reprocessamento, sem deriv_key, mesmo motivo do resumo/guia_md
    # acima -- nada aqui é editável à mão. `guia_md`/`guia_gerado_em`
    # continuam existindo como cache remontado por código a partir destes
    # campos + GuiaSecao/GuiaTopico (ver ai/guia_markdown.py), pra
    # export/corpus.py, export/exam_export.py e a rota /guia.md
    # continuarem funcionando sem mudança.
    guia_titulo: Mapped[str | None] = mapped_column(String, nullable=True)
    guia_arvore_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    guia_trechos_incompletos_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Narração em áudio do guia (TTS local via GPU, ver tts-service/). Um
    # mp3 por GuiaSecao, gerado pelo worker e cacheado em GUIA_AUDIO_DIR.
    # Comparado contra guia_gerado_em: mais antigo (ou nulo) = áudio
    # desatualizado, precisa regenerar -- mesma lógica de "carimbo de
    # versão" que o resto do guia já usa, sem precisar de hash de conteúdo
    # por seção.
    guia_audio_gerado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
    definitions: Mapped[list["Definition"]] = relationship(
        back_populates="lesson", cascade="all, delete-orphan"
    )
    guia_secoes: Mapped[list["GuiaSecao"]] = relationship(
        back_populates="lesson", order_by="GuiaSecao.ordem", cascade="all, delete-orphan"
    )
    guia_topicos: Mapped[list["GuiaTopico"]] = relationship(
        back_populates="lesson", order_by="GuiaTopico.ordem", cascade="all, delete-orphan"
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
    """A transcrição bruta de uma aula -- fonte de verdade de trabalho
    (PLANO.md). Editável por revisão humana desde a fase 8 (Whisper erra, e
    tudo depois -- guia, aula editada, cards -- herda o erro se ninguém
    corrigir antes). `aprovado_em` marca "revisado o suficiente pra
    alimentar IA"; reprocessar (nova transcrição do zero) com aprovação
    ativa exige confirmação explícita, que já limpa `aprovado_em` como
    parte do gesto -- sem isso a revisão manual sumiria silenciosamente."""

    __tablename__ = "transcript"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lesson.id"), nullable=False, unique=True)
    lesson: Mapped["Lesson"] = relationship(back_populates="transcript")

    engine: Mapped[str] = mapped_column(String, nullable=False)
    worker_name: Mapped[str] = mapped_column(String, nullable=False)
    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False)

    aprovado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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

    # Revisão humana (fase 8): editado_em só marca "você corrigiu este
    # trecho" pra UI mostrar o que já foi revisado -- o áudio original
    # continua a um toque, então não guardamos o texto pré-edição.
    editado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
CARD_TIPOS = ("flashcard", "discriminacao")


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
    outra tabela: os campos de SM-2 só importam a partir daí.

    `tipo` (fase 8b) discrimina duas origens sobre a mesma tabela — de
    novo sem duplicar linha nem criar outra tabela, mesmo padrão acima:
    "flashcard" é o card frente/verso de sempre; "discriminacao" nasce de
    um par confundível (`pares_confundiveis`) e usa frente/verso como o
    par sintetizado ("termo_a x termo_b: qual a diferença?" / eixo da
    distinção) mais os campos extras abaixo para a comparação lado a lado
    com áudio dos dois momentos. Os dois tipos correm pela mesma fila SM-2,
    aprovação e calibração sem código extra."""

    __tablename__ = "card_proposal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lesson.id"), nullable=False)
    lesson: Mapped["Lesson"] = relationship(back_populates="cards")

    deriv_key: Mapped[str] = mapped_column(String, nullable=False)
    tipo: Mapped[str] = mapped_column(String, nullable=False, default="flashcard")
    frente: Mapped[str] = mapped_column(Text, nullable=False)
    verso: Mapped[str] = mapped_column(Text, nullable=False)
    start_s: Mapped[float] = mapped_column(Float, nullable=False)
    end_s: Mapped[float] = mapped_column(Float, nullable=False)

    # Só para tipo="discriminacao": os dois termos, o eixo da distinção, e
    # os dois momentos de áudio -- deliberadamente separados de start_s/end_s
    # acima (que ficam 0.0, sem uso) em vez de reaproveitá-los pro termo_a,
    # porque start_s/end_s são NOT NULL e não dá pra distinguir "0.0 de
    # verdade" de "a IA não achou o intervalo". Aqui os quatro são nuláveis
    # de propósito -- nulo faz o botão de ouvir sumir em vez de mostrar um
    # horário inventado.
    termo_a: Mapped[str | None] = mapped_column(String, nullable=True)
    termo_b: Mapped[str | None] = mapped_column(String, nullable=True)
    eixo_distincao: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_s_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_s_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_s_b: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_s_b: Mapped[float | None] = mapped_column(Float, nullable=True)

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


class GuiaSecao(Base):
    """Seção do corpo do guia estruturado, em ordem -- sem deriv_key nem
    editado_em: nada aqui é editável à mão, cada reprocessamento apaga e
    recria por inteiro (mesmo motivo do resumo/guia_md em Lesson)."""

    __tablename__ = "guia_secao"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lesson.id"), nullable=False)
    lesson: Mapped["Lesson"] = relationship(back_populates="guia_secoes")

    ordem: Mapped[int] = mapped_column(Integer, nullable=False)
    titulo: Mapped[str] = mapped_column(String, nullable=False)
    corpo: Mapped[str] = mapped_column(Text, nullable=False)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class GuiaTopico(Base):
    """Item do sumário do guia estruturado. Ao contrário de GuiaSecao,
    carrega estado editável à mão: `secao_alvo_slug` é o alvo do link "ir
    para" no sumário -- por padrão nulo (usa a mesma posição do próprio
    tópico), corrigível na tela quando essa correspondência natural falha
    numa aula em particular. Guardado pelo título normalizado da seção, não
    por um número de posição cru, porque GuiaSecao não tem identidade
    estável entre reprocessamentos (é apagada e recriada por inteiro) -- um
    número cru poderia passar a apontar pra outra seção sem avisar
    ninguém. deriv_key por texto normalizado (mesmo padrão de
    LessonAssunto/Definition), porque não há intervalo de transcrição
    associado -- o conteúdo do guia pode reordenar/fundir trechos da
    fala."""

    __tablename__ = "guia_topico"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lesson.id"), nullable=False)
    lesson: Mapped["Lesson"] = relationship(back_populates="guia_topicos")

    deriv_key: Mapped[str] = mapped_column(String, nullable=False)
    ordem: Mapped[int] = mapped_column(Integer, nullable=False)
    titulo: Mapped[str] = mapped_column(String, nullable=False)
    secao_alvo_slug: Mapped[str | None] = mapped_column(String, nullable=True)

    editado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    orfao_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    versao_nova_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


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


# --- Fase 9: materiais e Google Docs ---
#
# `material` é a fonte única pra tudo que não é áudio (PLANO.md): PDF, foto,
# texto colado, link e Google Doc (origem=gdoc) vivem na mesma tabela. Um
# material não carrega matéria nem aula -- quem carrega isso é MaterialUse,
# porque o mesmo material serve mais de uma matéria (um resumo de
# "prescrição" vale em Civil e em Penal; preso a um subject_id ele valeria
# só numa). Mesmo princípio já usado em Assunto/AssuntoCobertura e em
# chunk-sem-subject_id.

MATERIAL_ORIGENS = ("pdf", "foto", "texto", "link", "gdoc")
MATERIAL_STATUSES = ("pendente", "ok", "erro")


class MaterialTipo(Base):
    """Vocabulário extensível (Decisões fechadas: tabela, não enum -- os
    tipos crescem ao longo do semestre). Seed em seed_data.py/MATERIAL_TIPOS,
    inserido pela migração como o seed de Subject."""

    __tablename__ = "material_tipo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    rotulo: Mapped[str] = mapped_column(String, nullable=False)
    icone: Mapped[str | None] = mapped_column(String, nullable=True)
    cor: Mapped[str | None] = mapped_column(String, nullable=True)


class Material(Base):
    """Fonte única pra tudo que não é áudio. Campos gdoc_id/gdoc_modified_time
    /synced_at/sync_error só valem quando origem="gdoc" -- é o que guia a
    sync incremental (`gdoc_modified_time` == o `modifiedTime` já visto ->
    nada mudou, pula). `path` guarda o arquivo local (pdf/foto); `url`
    guarda o link (origem=link) ou o link do Doc (origem=gdoc, calculado,
    não guardado); `conteudo_md` é o que a sync/edição manual preenche --
    fase 10 é quem passa a extrair de pdf/foto de verdade (`material_page`);
    aqui origem=pdf/foto só guarda o arquivo, sem OCR/visão ainda."""

    __tablename__ = "material"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tipo_id: Mapped[int | None] = mapped_column(ForeignKey("material_tipo.id"), nullable=True)
    tipo: Mapped["MaterialTipo | None"] = relationship()

    titulo: Mapped[str] = mapped_column(String, nullable=False)
    origem: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pendente")

    path: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    mime: Mapped[str | None] = mapped_column(String, nullable=True)
    conteudo_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Só quando origem="gdoc":
    gdoc_id: Mapped[str | None] = mapped_column(String, nullable=True)
    gdoc_modified_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Biblioteca (fase 10) -- só quando origem="pdf"/"foto" e o material é
    # uma porção de uma obra permanente: work_id nulo é "material avulso"
    # (não pertence a nenhum livro). pagina_inicial/pagina_final é o
    # intervalo que ESTE material ocupa dentro da obra (ex.: um capítulo
    # digitalizado cobre p. 247-290) -- é o que ordena as porções sozinho
    # e resolve pagina_obra de cada MaterialPage. ordem_manual só entra
    # quando a numeração real é desconhecida (foto de capítulo sem
    # paginação visível).
    work_id: Mapped[int | None] = mapped_column(ForeignKey("work.id"), nullable=True)
    work: Mapped["Work | None"] = relationship(back_populates="materials")
    pagina_inicial: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pagina_final: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ordem_manual: Mapped[int | None] = mapped_column(Integer, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    uses: Mapped[list["MaterialUse"]] = relationship(back_populates="material", cascade="all, delete-orphan")
    tags: Mapped[list["MaterialTag"]] = relationship(back_populates="material", cascade="all, delete-orphan")
    pages: Mapped[list["MaterialPage"]] = relationship(
        back_populates="material", order_by="MaterialPage.ordem", cascade="all, delete-orphan"
    )


class MaterialUse(Base):
    """Onde o material foi usado -- N:N com intervalo (PLANO.md): o mesmo
    arquivo pode valer pra mais de uma matéria, cada vínculo com seu próprio
    rótulo. `lesson_id` nulo é um vínculo válido e comum: "material da
    matéria, não de uma aula específica" (resumo geral, legislação,
    jurisprudência) -- PLANO.md, seção Google Docs. pagina_inicial/
    pagina_final chegam nulos até a fase 10 (biblioteca) começar a
    preenchê-los para recorte por página de obra; já nascem aqui pra essa
    fase não exigir outra migração."""

    __tablename__ = "material_use"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("material.id"), nullable=False)
    material: Mapped["Material"] = relationship(back_populates="uses")
    subject_id: Mapped[int] = mapped_column(ForeignKey("subject.id"), nullable=False)
    subject: Mapped["Subject"] = relationship()
    lesson_id: Mapped[int | None] = mapped_column(ForeignKey("lesson.id"), nullable=True)
    lesson: Mapped["Lesson | None"] = relationship()

    pagina_inicial: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pagina_final: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rotulo: Mapped[str | None] = mapped_column(String, nullable=True)
    lido_ate: Mapped[int | None] = mapped_column(Integer, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MaterialTag(Base):
    """Tags livres além do tipo (PLANO.md). Texto simples, sem tabela de
    vocabulário -- autocomplete (se um dia existir) lê os valores distintos
    já usados em vez de gerenciar uma lista separada."""

    __tablename__ = "material_tag"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("material.id"), nullable=False)
    material: Mapped["Material"] = relationship(back_populates="tags")
    tag: Mapped[str] = mapped_column(String, nullable=False)


# --- Fase 10: biblioteca -- livros, visão e citação ---
#
# A obra é permanente e sem matéria (PLANO.md, "Livros atravessam
# semestres"): o mesmo volume serve seis semestres e várias disciplinas.
# Quem carrega matéria e semestre é o uso (MaterialUse, já existente,
# fase 9) -- mesmo princípio já usado em Assunto/AssuntoCobertura e em
# chunk-sem-subject_id.
#
# A transcrição de página fotografada NÃO usa a API de visão da
# Anthropic -- decisão do usuário: o Claude Code lê a foto direto (Read
# tool já lê imagem) e devolve pela mesma ponte manual do resto do app.
# Ver RUNBOOK.md, "Transcrever páginas".

WORK_IMAGE_TIPOS = ("capa", "contracapa", "folha_rosto", "ficha", "sumario")
MATERIAL_PAGE_STATUSES = ("pendente", "ok", "erro")
MATERIAL_PAGE_EXTRAIDO_POR = ("nativo", "visao")


class Work(Base):
    """Obra bibliográfica -- permanente, sem matéria (PLANO.md). Uma obra,
    vários materiais (3 capítulos digitalizados em semestres diferentes =
    1 referência só). `referencia_manual` sobrepõe a montagem ABNT
    automática (`library/abnt.py`) para os casos em que ela erra:
    coletânea com organizador, tradução, e-book, volume de série."""

    __tablename__ = "work"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tipo: Mapped[str] = mapped_column(String, nullable=False, default="livro")

    titulo: Mapped[str] = mapped_column(String, nullable=False)
    subtitulo: Mapped[str | None] = mapped_column(String, nullable=True)
    autores: Mapped[str | None] = mapped_column(String, nullable=True)
    organizadores: Mapped[str | None] = mapped_column(String, nullable=True)
    tradutor: Mapped[str | None] = mapped_column(String, nullable=True)
    edicao: Mapped[str | None] = mapped_column(String, nullable=True)
    volume: Mapped[str | None] = mapped_column(String, nullable=True)
    tomo: Mapped[str | None] = mapped_column(String, nullable=True)
    local: Mapped[str | None] = mapped_column(String, nullable=True)
    editora: Mapped[str | None] = mapped_column(String, nullable=True)
    ano: Mapped[int | None] = mapped_column(Integer, nullable=True)
    isbn: Mapped[str | None] = mapped_column(String, nullable=True)
    doi: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    referencia_manual: Mapped[str | None] = mapped_column(Text, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    materials: Mapped[list["Material"]] = relationship(back_populates="work")
    images: Mapped[list["WorkImage"]] = relationship(back_populates="work", cascade="all, delete-orphan")
    sections: Mapped[list["WorkSection"]] = relationship(
        back_populates="work", order_by="WorkSection.ordem", cascade="all, delete-orphan"
    )


class WorkImage(Base):
    """Capa, contracapa, folha de rosto e ficha catalográfica da obra
    (PLANO.md). A capa faz a biblioteca virar estante visual; a ficha é a
    prova de origem quando a referência for questionada; o sumário
    fotografado alimenta `WorkSection` (hoje cadastrado à mão -- ler a
    foto do sumário automaticamente fica para quando a mesma ponte manual
    de páginas cobrir isso também)."""

    __tablename__ = "work_image"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("work.id"), nullable=False)
    work: Mapped["Work"] = relationship(back_populates="images")

    tipo: Mapped[str] = mapped_column(String, nullable=False)
    path: Mapped[str] = mapped_column(String, nullable=False)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class WorkSection(Base):
    """Estrutura da obra (do sumário) -- PLANO.md: "o sumário fotografado
    vira o esqueleto da obra". `nivel` é a profundidade hierárquica (1 =
    capítulo, 2 = subseção...). Cadastro manual por ora; o mapa de
    cobertura (o que falta) é calculado comparando os intervalos daqui
    contra os materiais já subidos, não guardado."""

    __tablename__ = "work_section"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("work.id"), nullable=False)
    work: Mapped["Work"] = relationship(back_populates="sections")

    ordem: Mapped[int] = mapped_column(Integer, nullable=False)
    nivel: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    titulo: Mapped[str] = mapped_column(String, nullable=False)
    pagina_inicial: Mapped[int] = mapped_column(Integer, nullable=False)
    pagina_final: Mapped[int | None] = mapped_column(Integer, nullable=True)


class MaterialPage(Base):
    """Uma página de um material (PLANO.md): foto ou página de PDF, uma
    linha por página. `pagina_obra` é a numeração real do livro
    (`material.pagina_inicial + ordem`, quando conhecida -- nula se o
    material usa `ordem_manual`). `extraido_por` distingue texto pego
    direto da camada nativa do PDF (`nativo`, sem custo, sem revisão
    necessária) de texto transcrito por leitura de imagem (`visao`, hoje
    via Claude Code na ponte manual -- ver RUNBOOK.md). `editado_em`
    protege sua correção: refazer a transcrição daquela página nunca
    sobrescreve o que você já corrigiu (mesma garantia do resto do app)."""

    __tablename__ = "material_page"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("material.id"), nullable=False)
    material: Mapped["Material"] = relationship(back_populates="pages")

    ordem: Mapped[int] = mapped_column(Integer, nullable=False)
    pagina_obra: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_path: Mapped[str] = mapped_column(String, nullable=False)
    texto: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraido_por: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pendente")

    ai_call_id: Mapped[int | None] = mapped_column(ForeignKey("ai_call.id"), nullable=True)
    erro: Mapped[str | None] = mapped_column(Text, nullable=True)
    editado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# --- Fase 11: glossário -- a definição do seu professor ---
#
# "O termo é apenas a entrada lexical... as definições são muitas,
# penduradas nele" (PLANO.md). Mesmo padrão já usado em Assunto (fase 8):
# a entidade global casa por slug normalizado, e o que muda com o tempo
# (aqui, a definição; lá, a cobertura) é uma tabela à parte, muitas por
# entidade global. `DEFINITION_STATUSES`/`origem` espelham
# CARD_STATUSES: proposta da IA entra pendente ("proposto"), na mesma
# tela de aprovação; criada por você entra direto "ativo", sem
# autoaprovação.

DEFINITION_STATUSES = ("proposto", "ativo", "descartado")
DEFINITION_ORIGENS = ("ia", "manual")


class Term(Base):
    """A entrada lexical -- uma por grafia em todo o curso (PLANO.md).
    `slug` é a chave de casamento (mesmo `normalize_slug` de assuntos.py);
    `rotulo` é só exibição e pode ser corrigido sem quebrar o casamento.
    `destacar=False` é o "botão por verbete pra parar de destacar" --
    continua no glossário e na busca, só some do texto corrido."""

    __tablename__ = "term"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    rotulo: Mapped[str] = mapped_column(String, nullable=False)
    destacar: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    aliases: Mapped[list["TermAlias"]] = relationship(back_populates="term", cascade="all, delete-orphan")
    definitions: Mapped[list["Definition"]] = relationship(
        back_populates="term", order_by="Definition.criado_em", cascade="all, delete-orphan"
    )


class TermAlias(Base):
    """Variante de flexão (PLANO.md: "negócio jurídico"/"negócios
    jurídicos") -- `alias` já normalizado (sem acento, minúsculo, espaço
    preservado) pra casar contra o texto renderizado, também já
    normalizado, em `glossary/matcher.py`. Único globalmente: a mesma
    grafia não pode apontar pra dois termos ao mesmo tempo, senão o
    casamento fica ambíguo."""

    __tablename__ = "term_alias"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("term.id"), nullable=False)
    term: Mapped["Term"] = relationship(back_populates="aliases")
    alias: Mapped[str] = mapped_column(String, nullable=False, unique=True)


class Definition(Base):
    """Uma definição, amarrada à matéria/aula/página e à citação literal
    (PLANO.md: "nada de 'definição canônica', há um histórico"). Segue o
    padrão de deriv_key/reconcile das fases 6/8b: proposta da IA
    (`origem="ia"`, `status="proposto"`) entra pendente de aprovação;
    reprocessar a aula preserva o que você editou/aceitou e marca órfão o
    que sumiu. Criada por você (`origem="manual"`) nasce direto "ativo"
    e sem `deriv_key" (nada pra reconciliar).

    `term_id` nasce nulo numa proposta da IA -- mesmo padrão de
    `LessonAssunto.assunto_id` (fase 8): o texto que a IA propôs
    (`termo_proposto`) fica editável na tela de aprovação, e só vira um
    `Term` de verdade (achado ou criado por slug) no momento de aceitar,
    pra erro de grafia da IA não poluir o glossário global antes de você
    poder corrigir. `variantes_propostas_json` guarda as variantes de
    flexão que a IA sugeriu (PLANO.md: "a IA propõe as variantes"),
    também aplicadas como `TermAlias` só na aceitação."""

    __tablename__ = "definition"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    term_id: Mapped[int | None] = mapped_column(ForeignKey("term.id"), nullable=True)
    term: Mapped["Term | None"] = relationship(back_populates="definitions")
    termo_proposto: Mapped[str | None] = mapped_column(String, nullable=True)
    variantes_propostas_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    deriv_key: Mapped[str | None] = mapped_column(String, nullable=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subject.id"), nullable=True)
    subject: Mapped["Subject | None"] = relationship()
    lesson_id: Mapped[int | None] = mapped_column(ForeignKey("lesson.id"), nullable=True)
    lesson: Mapped["Lesson | None"] = relationship(back_populates="definitions")
    material_id: Mapped[int | None] = mapped_column(ForeignKey("material.id"), nullable=True)
    material: Mapped["Material | None"] = relationship()

    start_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    pagina: Mapped[int | None] = mapped_column(Integer, nullable=True)

    definicao_md: Mapped[str] = mapped_column(Text, nullable=False)
    citacao_literal: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Default espelha CARD_STATUSES/etc: o caminho comum por `reconcile()`
    # é a proposta da IA, então uma linha nova sem status explícito precisa
    # nascer "proposto" -- não "ativo" -- senão reconcile() insere pulando
    # a aprovação. A criação manual (routes/glossary.py) passa
    # status="ativo", origem="manual" explicitamente, fora do reconcile.
    status: Mapped[str] = mapped_column(String, nullable=False, default="proposto")
    origem: Mapped[str] = mapped_column(String, nullable=False, default="ia")

    editado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    orfao_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    versao_nova_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TermPin(Base):
    """Preferência fixada (PLANO.md): resolve na mão qual definição abre
    primeiro numa matéria específica, sobrepondo a heurística de
    ordenação. Uma por (termo, matéria)."""

    __tablename__ = "term_pin"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("term.id"), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subject.id"), nullable=False)
    definition_id: Mapped[int] = mapped_column(ForeignKey("definition.id"), nullable=False)

    __table_args__ = (UniqueConstraint("term_id", "subject_id", name="uq_term_pin_term_subject"),)


# Fase 13 -- produção. "Isso é produção, não reconhecimento" (PLANO.md):
# Feynman por voz e dissertativa avaliada compartilham a mesma forma --
# você produz, a IA compara contra a definição/rubrica de verdade e
# aponta o que faltou, citando o minuto da aula. Nenhuma das duas usa
# deriv_key/reconcile (não são derivadas de transcrição por
# reprocessamento, são tentativas suas, cada uma sua própria linha —
# mesma lógica de ReviewLog: histórico, não estado a substituir).

FEYNMAN_STATUSES = ("transcrito", "avaliado", "erro")


class FeynmanAttempt(Base):
    """Uma gravação curta explicando um termo em voz alta (PLANO.md,
    "Feynman por voz"). `audio_path`/`transcript_text` vêm do ASR curto
    (faster-whisper small, CPU da VPS -- `app/media/asr.py`), sempre
    automático (não é chamada paga, não passa pela ponte manual). A
    AVALIAÇÃO contra a definição do professor é que segue a ponte manual
    de sempre (`ai_call_id` fica nulo até isso acontecer). Comparado
    contra TODAS as definições ativas do termo, não uma só -- "todas as
    definições, lado a lado" vale aqui também."""

    __tablename__ = "feynman_attempt"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("term.id"), nullable=False)
    term: Mapped["Term"] = relationship()

    audio_path: Mapped[str] = mapped_column(String, nullable=False)
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="transcrito")

    pontos_cobertos_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    pontos_faltantes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    divergencias_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    comentario_geral: Mapped[str | None] = mapped_column(Text, nullable=True)
    erro: Mapped[str | None] = mapped_column(Text, nullable=True)

    ai_call_id: Mapped[int | None] = mapped_column(ForeignKey("ai_call.id"), nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    avaliado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DissertativaQuestion(Base):
    """Questão no estilo do professor, com rubrica (PLANO.md, "dissertativa
    avaliada") -- gerada a partir de uma aula (`lesson_id`) ou de um
    assunto inteiro (`assunto_id`, via `context/window.py`, mesmo recorte
    literal usado em fase 8a), nunca das duas ao mesmo tempo."""

    __tablename__ = "dissertativa_question"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Nulo quando gerada a partir de um assunto (PLANO.md: assunto é
    # global, atravessa matérias -- não faria sentido forçar uma só aqui).
    # Preenchido com `lesson.subject_id` quando gerada a partir de uma aula.
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subject.id"), nullable=True)
    subject: Mapped["Subject | None"] = relationship()
    lesson_id: Mapped[int | None] = mapped_column(ForeignKey("lesson.id"), nullable=True)
    lesson: Mapped["Lesson | None"] = relationship()
    assunto_id: Mapped[int | None] = mapped_column(ForeignKey("assunto.id"), nullable=True)
    assunto: Mapped["Assunto | None"] = relationship()

    enunciado: Mapped[str] = mapped_column(Text, nullable=False)
    rubrica_json: Mapped[str] = mapped_column(Text, nullable=False)

    ai_call_id: Mapped[int | None] = mapped_column(ForeignKey("ai_call.id"), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    attempts: Mapped[list["DissertativaAttempt"]] = relationship(
        back_populates="question", order_by="DissertativaAttempt.criado_em", cascade="all, delete-orphan"
    )


class DissertativaAttempt(Base):
    """Uma tentativa de resposta -- histórico, nunca sobrescreve a
    anterior (PLANO.md: "histórico de tentativas"). `status` segue o
    mesmo vocabulário de FeynmanAttempt: escrita entra "respondido",
    correção pela ponte manual leva a "avaliado"."""

    __tablename__ = "dissertativa_attempt"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("dissertativa_question.id"), nullable=False)
    question: Mapped["DissertativaQuestion"] = relationship(back_populates="attempts")

    resposta_texto: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="respondido")

    pontos_cobertos_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    pontos_faltantes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    comentario: Mapped[str | None] = mapped_column(Text, nullable=True)

    ai_call_id: Mapped[int | None] = mapped_column(ForeignKey("ai_call.id"), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    avaliado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# Fase 14 -- provas, plano regressivo e exportação. "Os assuntos emergem
# das aulas, não de um formulário" continua valendo: a ementa é sempre
# OPCIONAL e só ENRIQUECE Assunto/AssuntoCobertura que já existem (ou
# nascem na hora, como propostas normais) -- nunca um pré-requisito pro
# plano regressivo, que já funciona só com os assuntos emergidos.


class Ementa(Base):
    """A grade oficial de tópicos de uma matéria, cadastrada por você
    (PLANO.md: "cadastro opcional"). Uma por `Subject` -- cada oferta da
    disciplina (um semestre) tem sua própria, mesmo se o conteúdo se
    repetir de um semestre pro outro."""

    __tablename__ = "ementa"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subject.id"), nullable=False, unique=True)
    subject: Mapped["Subject"] = relationship()

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    topicos: Mapped[list["EmentaTopico"]] = relationship(
        back_populates="ementa", order_by="EmentaTopico.ordem", cascade="all, delete-orphan"
    )


class EmentaTopico(Base):
    """Um tópico oficial, na ordem do plano de ensino. `assunto_id` liga
    ao `Assunto` correspondente -- casado por slug na importação
    (`ementa.py::import_ementa`) ou achado/criado na hora se o tópico
    ainda não existe como assunto emergido de nenhuma aula (nasce com
    cobertura `status="pendente"`, "ementa, mas ainda não dado")."""

    __tablename__ = "ementa_topico"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ementa_id: Mapped[int] = mapped_column(ForeignKey("ementa.id"), nullable=False)
    ementa: Mapped["Ementa"] = relationship(back_populates="topicos")
    assunto_id: Mapped[int] = mapped_column(ForeignKey("assunto.id"), nullable=False)
    assunto: Mapped["Assunto"] = relationship()

    titulo: Mapped[str] = mapped_column(String, nullable=False)
    ordem: Mapped[int] = mapped_column(Integer, nullable=False)


class Exam(Base):
    """Uma prova com data e escopo por assunto (PLANO.md, "plano
    regressivo"). `titulo` é livre ("P1", "Final") -- não há vocabulário
    fechado porque cada curso nomeia diferente."""

    __tablename__ = "exam"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subject.id"), nullable=False)
    subject: Mapped["Subject"] = relationship()

    titulo: Mapped[str] = mapped_column(String, nullable=False)
    data: Mapped[date] = mapped_column(Date, nullable=False)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    escopo: Mapped[list["ExamScope"]] = relationship(back_populates="exam", cascade="all, delete-orphan")


class ExamScope(Base):
    """Um assunto dentro do escopo de uma prova -- N:N simples, sem
    campo extra (a data/cobertura já vêm de `AssuntoCobertura`)."""

    __tablename__ = "exam_scope"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exam.id"), nullable=False)
    exam: Mapped["Exam"] = relationship(back_populates="escopo")
    assunto_id: Mapped[int] = mapped_column(ForeignKey("assunto.id"), nullable=False)
    assunto: Mapped["Assunto"] = relationship()

    __table_args__ = (UniqueConstraint("exam_id", "assunto_id", name="uq_exam_scope_exam_assunto"),)


USER_ROLES = ("usuario", "admin")
USER_STATUSES = ("pendente", "aprovado", "recusado", "revogado")


class User(Base):
    """Login humano por usuário+senha (PLANO.md, seção "Acesso" -- o
    "Convite" que ali foi deliberadamente adiado pro pós-v1). Cadastro
    nasce em status="pendente" -- só um admin aprova, recusa, revoga ou
    concede validade limitada (`expira_em`). Mesmo idioma de
    `Subject.encerrada_em`: nulo = sem prazo, comparado contra agora na
    hora do login (não um job/cron -- o acesso já vencido só precisa
    parar de autenticar, não precisa de limpeza ativa)."""

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    senha_hash: Mapped[str] = mapped_column(String, nullable=False)
    papel: Mapped[str] = mapped_column(String, nullable=False, default="usuario")
    status: Mapped[str] = mapped_column(String, nullable=False, default="pendente")
    expira_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    aprovado_por_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    aprovado_por: Mapped["User | None"] = relationship(remote_side=[id])

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decidido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
