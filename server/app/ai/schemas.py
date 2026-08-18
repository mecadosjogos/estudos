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
    """Capturado desde já (a mesma passada já enxerga o ato definitório),
    mas o glossário de verdade — Aho-Corasick, fusão, aba própria — é a
    fase 11. Por ora só guardamos a proposta bruta em AiCall.raw_response_json."""

    termo: str
    definicao: str
    citacao_literal: str
    start_s: float
    variantes: list[str] = Field(default_factory=list)


class ConfusablePairOut(BaseModel):
    """Fase 8. Capturado agora, usado depois."""

    termo_a: str
    termo_b: str
    eixo_distincao: str


class LessonProcessingOutput(BaseModel):
    """A resposta inteira de uma passada. `aula_editada` é o que fase 6
    persiste; termos/pares/mapa/assuntos ficam guardados crus em
    AiCall.raw_response_json até suas fases chegarem."""

    resumo: str
    aula_editada: list[EditedBlockOut]
    indice: list[OutlineItemOut]
    artigos: list[ArticleMentionOut] = Field(default_factory=list)
    datas_anunciadas: list[AnnouncementOut] = Field(default_factory=list)
    cards: list[CardOut] = Field(default_factory=list)
    termos: list[TermDefinitionOut] = Field(default_factory=list)
    pares_confundiveis: list[ConfusablePairOut] = Field(default_factory=list)
    mapa_mermaid: str | None = None
    assuntos: list[str] = Field(default_factory=list)
