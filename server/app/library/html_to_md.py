"""HTML -> Markdown (PLANO.md, "Google Docs": exporta em text/html ->
Markdown, preserva títulos, negrito, listas). O Doc original continua a um
clique (Abrir no Docs / Ver aqui) como fonte de verdade — isto é só a cópia
de trabalho que entra na busca e nas chamadas de IA.

O export HTML do Google Docs não aninha listas: cada nível vira um `<ul>`
irmão (classe `lst-kix_<lista>-<nível>`) e o recuo que você vê no Docs mora
só no CSS (`margin-left`/`text-indent` por classe, múltiplos de 36pt). O
markdownify sozinho achata tudo num nível só — por isso o HTML do Docs é
percorrido bloco a bloco aqui, e cada linha ganha 4 espaços por nível de
recuo visual (mesma convenção do guia_md).
"""

import re

from bs4 import BeautifulSoup
from markdownify import markdownify

INDENT = "    "
STEP_PT = 36.0  # um "Tab" de recuo no Google Docs

_LIST_CLASS = re.compile(r"^lst-kix_(.+)-(\d+)$")
_HEADING = re.compile(r"^h([1-6])$")


def html_to_markdown(html: str) -> str:
    if "lst-kix_" not in html and "doc-content" not in html:
        return markdownify(html, heading_style="ATX").strip()
    return _google_doc_to_markdown(html)


def _css_by_class(soup: BeautifulSoup) -> dict[str, dict[str, float]]:
    """`.c5{margin-left:72pt;...}` -> {"c5": {"margin-left": 72.0}}."""
    styles: dict[str, dict[str, float]] = {}
    css = "\n".join(tag.get_text() for tag in soup.find_all("style"))
    for selector, body in re.findall(r"\.([\w-]+)\s*\{([^}]*)\}", css):
        for prop in ("margin-left", "text-indent"):
            match = re.search(rf"(?:^|;)\s*{prop}\s*:\s*(-?[\d.]+)pt", body)
            if match:
                styles.setdefault(selector, {})[prop] = float(match.group(1))
    return styles


def _pt(tag, prop: str, styles: dict[str, dict[str, float]]) -> float | None:
    inline = re.search(rf"{prop}\s*:\s*(-?[\d.]+)pt", tag.get("style", ""))
    if inline:
        return float(inline.group(1))
    values = [styles[c][prop] for c in tag.get("class", []) if prop in styles.get(c, {})]
    return values[-1] if values else None


def _inline(tag) -> str:
    text = markdownify(
        tag.decode_contents(), heading_style="ATX", escape_asterisks=False, escape_underscores=False
    )
    text = text.replace("\xa0", " ").replace("\n", " ")
    return text.rstrip()


def _google_doc_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    styles = _css_by_class(soup)
    root = soup.body or soup
    lines: list[str] = []
    counters: dict[tuple[str, int], int] = {}

    for block in root.find_all(recursive=False):
        name = block.name
        if name in ("ul", "ol"):
            list_id, list_level = "", 0
            for cls in block.get("class", []):
                match = _LIST_CLASS.match(cls)
                if match:
                    list_id, list_level = match.group(1), int(match.group(2))
            if "start" in block.get("class", []):
                counters.pop((list_id, list_level), None)
            for li in block.find_all("li", recursive=False):
                margin = _pt(li, "margin-left", styles)
                level = round(margin / STEP_PT) - 1 if margin is not None else list_level
                level = max(level, 0)
                if name == "ol":
                    n = counters.get((list_id, list_level), 0) + 1
                    counters[(list_id, list_level)] = n
                    marker = f"{n}."
                else:
                    marker = "*"
                lines.append(f"{INDENT * level}{marker} {_inline(li).strip()}")
        elif name == "p" or _HEADING.match(name or ""):
            text = _inline(block)
            if not text.strip():
                lines.append("")
                continue
            indent_pt = (_pt(block, "margin-left", styles) or 0) + (_pt(block, "text-indent", styles) or 0)
            level = max(round(indent_pt / STEP_PT), 0)
            heading = _HEADING.match(name)
            prefix = "#" * int(heading.group(1)) + " " if heading else ""
            lines.append(f"{INDENT * level}{prefix}{text}")
        else:
            lines.extend(markdownify(str(block), heading_style="ATX").strip().splitlines())

    # colapsa linhas em branco repetidas, mantendo o recuo das linhas com texto
    out: list[str] = []
    for line in lines:
        if not line.strip() and out and not out[-1].strip():
            continue
        out.append(line)
    return "\n".join(out).strip("\n")
