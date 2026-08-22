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
