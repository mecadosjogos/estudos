"""Render HTML para PDF (PLANO.md, fase 14: "aula editada e apanhado do
escopo da prova em PDF para estudar no papel na véspera"). Usa
`fitz.Story` (PyMuPDF, já dependência do projeto desde a fase 10 --
`library/pdf.py`) em vez de trazer uma biblioteca nova só pra isto:
`Story` já lê HTML+CSS simples e resolve paginação sozinho."""

import io

import fitz

_BASE_CSS = """
body { font-family: sans-serif; font-size: 11pt; line-height: 1.5; }
h1 { font-size: 16pt; margin-bottom: 0.3em; }
h2 { font-size: 13pt; margin-top: 1em; margin-bottom: 0.3em; border-bottom: 1px solid #ccc; }
p { margin: 0.4em 0; }
.muted { color: #666; font-size: 9pt; }
.badge { font-size: 8pt; border: 1px solid #999; border-radius: 3px; padding: 0 0.3em; margin-right: 0.3em; }
ul { margin: 0.3em 0; padding-left: 1.4em; }
"""


def render_html_to_pdf(html: str, extra_css: str = "") -> bytes:
    story = fitz.Story(html=html, user_css=_BASE_CSS + extra_css)
    buf = io.BytesIO()
    writer = fitz.DocumentWriter(buf)
    rect = fitz.paper_rect("a4")
    where = rect + (36, 36, -36, -36)
    more = True
    while more:
        device = writer.begin_page(rect)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()
    return buf.getvalue()


def add_header_footer(pdf_bytes: bytes, text: str) -> bytes:
    """Escreve `text` centralizado no topo e no rodapé de toda página --
    pós-processamento em cima do PDF já pronto, porque `fitz.Story` não
    tem cabeçalho/rodapé de página nativo (diferente de `@page` no CSS
    paginado). `text` pode ter várias linhas (`\\n`); cada linha é
    centralizada e empilhada com 10pt de espaçamento, sempre cabendo
    dentro da margem de 36pt que `render_html_to_pdf` já reserva (topo a
    partir de y=12, rodapé terminando em y=altura-14), então não precisa
    encolher a área de conteúdo nem mudar `render_html_to_pdf`."""
    linhas = text.split("\n")
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        rect = page.rect
        for i, linha in enumerate(linhas):
            width = fitz.get_text_length(linha, fontsize=8)
            x = (rect.width - width) / 2
            page.insert_text((x, 12 + i * 10), linha, fontsize=8, color=(0.4, 0.4, 0.4))
            page.insert_text(
                (x, rect.height - 14 - (len(linhas) - 1 - i) * 10),
                linha, fontsize=8, color=(0.4, 0.4, 0.4),
            )
    result = doc.tobytes()
    doc.close()
    return result
