"""Liga os nós do mapa de taxonomia (Mermaid) aos verbetes do glossário
(PLANO.md, fase 15: "com os nós ligados aos verbetes do glossário").

Não é um parser de gramática Mermaid completo -- reconhece só o padrão
comum de definição de nó num flowchart (`Id[Rótulo]`, `Id(Rótulo)`,
`Id{Rótulo}`, `Id([Rótulo])`, `Id[[Rótulo]]` etc.) via regex, o bastante
pra achar "rótulo do nó" e casar contra o glossário; simplificação
deliberada dado que a IA sempre gera o mesmo estilo de flowchart simples
pedido no prompt."""

import re

from sqlalchemy.orm import Session

from .index import load_active_variants
from .normalize import normalize_char_preserving

_NODE_RE = re.compile(
    r'^\s*([A-Za-z0-9_]+)\s*(?:\[\[|\(\(|\[\(|\(\[|[\[\(\{])\s*"?([^"\[\]\(\)\{\}]+?)"?\s*(?:\]\]|\)\)|\)\]|\[\)|[\]\)\}])',
)


def _term_lookup(session: Session) -> dict[str, int]:
    lookup: dict[str, int] = {}
    for variant in load_active_variants(session):
        lookup.setdefault(variant.normalized, variant.term_id)
    return lookup


def link_mermaid_nodes_to_glossary(mermaid_src: str, session: Session) -> str:
    if not mermaid_src or not mermaid_src.strip():
        return mermaid_src

    lookup = _term_lookup(session)
    if not lookup:
        return mermaid_src

    click_lines = []
    seen_node_ids: set[str] = set()
    for line in mermaid_src.splitlines():
        match = _NODE_RE.match(line)
        if not match:
            continue
        node_id, label = match.group(1), match.group(2).strip()
        if node_id in seen_node_ids:
            continue
        term_id = lookup.get(normalize_char_preserving(label))
        if term_id is None:
            continue
        seen_node_ids.add(node_id)
        click_lines.append(f'click {node_id} "/termos/{term_id}" "_self"')

    if not click_lines:
        return mermaid_src
    return mermaid_src.rstrip() + "\n" + "\n".join(click_lines) + "\n"
