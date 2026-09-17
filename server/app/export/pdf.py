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
ol { margin: 0.3em 0; padding-left: 1.4em; }
h3 { font-size: 12pt; margin-top: 0.9em; margin-bottom: 0.2em; }
h4 { font-size: 11.5pt; margin-top: 0.7em; margin-bottom: 0.2em; }
h5, h6 { font-size: 11pt; margin-top: 0.6em; margin-bottom: 0.2em; color: #555; }
.guia-nivel { margin-left: 12pt; }
table { border-collapse: collapse; margin: 0.4em 0; }
th, td { border: 1px solid #bbb; padding: 2pt 4pt; vertical-align: top; text-align: left; }
th { background-color: #eeeeee; }
blockquote { margin: 0.4em 0; padding: 2pt 8pt; border-left: 2pt solid #999; color: #444; }
"""

# Blocos rotulados do guia (app/markdown_render.py) -- mesmas cores da tela
# (static/style.css), com hex fixo: o motor HTML do MuPDF não entende
# variável CSS nem color-mix().
_BLOCOS_GUIA = {
    "lei": ("#9f1239", "#fdf0f3"),
    "definicao": ("#2563eb", "#eef3fd"),
    "exemplo": ("#15803d", "#eef7f1"),
    "atencao": ("#b45309", "#fdf4ea"),
    "aluno": ("#6b6b70", "#f3f3f4"),
    "material": ("#0f766e", "#ecf6f5"),
}
_BASE_CSS += ".guia-bloco { margin: 0.6em 0; padding: 4pt 8pt; border-left: 3pt solid #999; }\n"
_BASE_CSS += ".guia-bloco p { margin: 0.2em 0; }\n"
_BASE_CSS += ".guia-rotulo { font-size: 9pt; font-weight: bold; }\n"
for _tipo, (_cor, _fundo) in _BLOCOS_GUIA.items():
    _BASE_CSS += (
        f".guia-bloco--{_tipo} {{ border-left-color: {_cor}; background-color: {_fundo}; }}\n"
        f".guia-bloco--{_tipo} .guia-rotulo {{ color: {_cor}; }}\n"
    )


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
