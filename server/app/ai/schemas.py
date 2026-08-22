"""Schema da saída estruturada de uma passada de processamento de aula
(PLANO.md, fase 6). Usado tanto para gerar o JSON Schema da chamada real da
API quanto para validar a resposta — automática ou colada manualmente.

Vocabulário fechado pros tipos de bloco (Integridade do design, não do
banco): sem isso cada aula sai com uma estética diferente.
"""

from pydantic import BaseModel, Field

BLOCK_TIPOS = ("destaque-prova", "ditado", "conceito", "exemplo", "atencao", "normal")


class EditedBlockOut(BaseModel):
    tipo: str = Field(description="Um de: " + ", ".join(BLOCK_TIPOS))
    texto: str
    start_s: float
    end_s: float


class OutlineItemOut(BaseModel):
    titulo: str
    start_s: float
    end_s: float


class ArticleMentionOut(BaseModel):
    texto_citado: str
    start_s: float


class AnnouncementOut(BaseModel):
    texto: str
    data_anunciada: str | None = Field(default=None, description="ISO 8601 (AAAA-MM-DD) se der pra inferir")
    start_s: float


class CardOut(BaseModel):
    frente: str
    verso: str
    start_s: float
    end_s: float


class TermDefinitionOut(BaseModel):
    """Só registre um termo quando o professor efetivamente o DEFINIU, não
    quando apenas o mencionou de passagem -- o gatilho é o ato definitório
    ("isso a gente chama de...", "define-se X como...", "o conceito de X
    é..."). `citacao_literal` é a fala exata do professor nesse instante
    (não parafraseada); `start_s` é o momento dela, pra tocar o áudio
    depois. `variantes` são as flexões de grafia do MESMO termo que
    provavelmente aparecem no resto da aula ou de aulas futuras (ex.:
    termo "negócio jurídico" -> variantes ["negócios jurídicos"]) -- sem
    stemmer, cada uma casa em fronteira de palavra."""

    termo: str
    definicao: str
    citacao_literal: str
    start_s: float
    variantes: list[str] = Field(default_factory=list)


class ConfusablePairOut(BaseModel):
    """Fase 8b: vira card de discriminação com comparação lado a lado. Os
    quatro timestamps são opcionais -- respostas coladas antes desta versão
    do schema não os tinham, e o par ainda assim é utilizável, só sem os
    botões de ouvir o original de cada termo."""

    termo_a: str
    termo_b: str
    eixo_distincao: str
    start_s_a: float | None = Field(
        default=None, description="Instante em que termo_a foi explicado/contrastado, se identificável"
    )
    end_s_a: float | None = None
    start_s_b: float | None = Field(
        default=None, description="Instante em que termo_b foi explicado/contrastado, se identificável"
    )
    end_s_b: float | None = None


class LessonProcessingOutput(BaseModel):
    """A resposta inteira de uma passada. `aula_editada`, `cards`,
    `pares_confundiveis`, `assuntos` e `termos` já são persistidos em
    tabela própria (fases 6/8a/8b/11); `mapa_mermaid` ainda fica guardado
    cru em AiCall.raw_response_json até sua fase (15) chegar.

    `guia_md` (antes uma segunda chamada separada, `ai/guia.py`) entra na
    MESMA leitura da transcrição -- ler a mesma fonte duas vezes pra gerar
    dois artefatos era desperdício, sobretudo na ponte manual, onde "ler"
    é o próprio agente processando ~27k tokens de novo do zero. Continua
    sendo um artefato à parte no banco (`Lesson.guia_md`, regenerado por
    inteiro, sem deriv_key) -- só a chamada que virou uma só."""

    resumo: str
    aula_editada: list[EditedBlockOut]
    indice: list[OutlineItemOut]
    guia_md: str
    artigos: list[ArticleMentionOut] = Field(default_factory=list)
    datas_anunciadas: list[AnnouncementOut] = Field(default_factory=list)
    cards: list[CardOut] = Field(default_factory=list)
    termos: list[TermDefinitionOut] = Field(default_factory=list)
    pares_confundiveis: list[ConfusablePairOut] = Field(default_factory=list)
    mapa_mermaid: str | None = None
    assuntos: list[str] = Field(default_factory=list)


class FeynmanFeedbackOut(BaseModel):
    """Fase 13 -- avaliação de uma explicação falada contra a(s)
    definição(ões) do professor. `pontos_faltantes` vazio é um resultado
    válido (explicação completa), não um sinal de que algo deu errado."""

    pontos_cobertos: list[str] = Field(default_factory=list)
    pontos_faltantes: list[str] = Field(default_factory=list)
    divergencias_terminologicas: list[str] = Field(default_factory=list)
    comentario_geral: str = ""


class DissertativaQuestionOut(BaseModel):
    """Fase 13 -- questão no estilo do professor, gerada a partir do
    recorte literal de uma aula ou de um assunto inteiro."""

    enunciado: str
    rubrica: list[str]


class DissertativaCorrectionOut(BaseModel):
    """Fase 13 -- correção de uma resposta dissertativa contra a rubrica
    da questão."""

    pontos_cobertos: list[str] = Field(default_factory=list)
    pontos_faltantes: list[str] = Field(default_factory=list)
    comentario: str = ""
