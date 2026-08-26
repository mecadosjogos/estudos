"""Tipos compartilhados entre `graph.py` (orquestrador) e `cooccurrence.py`
(camada opcional) -- vivem aqui, não em nenhum dos dois, pra os dois
poderem importar um do outro sem ciclo."""

from dataclasses import dataclass, field


@dataclass
class GraphNode:
    id: str  # "term:12" ou "assunto:7" -- prefixo evita colisão de PK entre as duas tabelas
    tipo: str  # "term" | "assunto"
    label: str
    subject_ids: list[int] = field(default_factory=list)


@dataclass
class GraphEdge:
    a: str
    b: str
    peso: int
    origem: str = "coocorrencia"  # "taxonomia" | "discriminacao" | "assunto" | "coocorrencia"
    rotulo: str | None = None
    lesson_ids: list[int] = field(default_factory=list)
    direcionado: bool = False  # só True pra origem="taxonomia" -- a seta carrega sentido real


def node_id(tipo: str, id_: int) -> str:
    return f"{tipo}:{id_}"
