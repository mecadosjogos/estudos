"""HTML -> Markdown (PLANO.md, "Google Docs": exporta em text/html ->
Markdown, preserva títulos, negrito, listas). O Doc original continua a um
clique (Abrir no Docs / Ver aqui) como fonte de verdade — isto é só a cópia
de trabalho que entra na busca e nas chamadas de IA.
"""

from markdownify import markdownify


def html_to_markdown(html: str) -> str:
    return markdownify(html, heading_style="ATX").strip()
