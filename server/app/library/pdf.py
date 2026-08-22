"""PDF (PLANO.md, "Biblioteca"): extrai texto nativo quando existe camada
de texto (slide exportado, e-book, artigo); quando não existe (capítulo
fotocopiado, apostila antiga escaneada), renderiza a página como imagem e
ela segue o mesmo caminho de uma foto — transcrição por leitura de imagem,
na ponte manual (ver RUNBOOK.md, "Transcrever páginas"). Nunca mistura os
dois: cada página do PDF é OU nativa OU tratada como imagem, decidido
página a página, porque um PDF pode ter capítulos digitados e um anexo
escaneado no mesmo arquivo.
"""

import fitz  # PyMuPDF -- renderização de página como imagem
from pypdf import PdfReader  # extração de texto nativo

MIN_CHARS_FOR_NATIVE_TEXT = 20  # por página -- abaixo disso, trata como escaneada


def page_count(pdf_path: str) -> int:
    return len(PdfReader(pdf_path).pages)


def has_native_text(pdf_path: str) -> list[bool]:
    """Uma entrada por página: True se ela tem camada de texto extraível
    o bastante pra confiar (PDF nativo/exportado), False se é imagem
    escaneada (ou o texto extraído é ruído demais pra ser confiável)."""
    reader = PdfReader(pdf_path)
    return [len((page.extract_text() or "").strip()) >= MIN_CHARS_FOR_NATIVE_TEXT for page in reader.pages]


def extract_native_text(pdf_path: str, page_index: int) -> str:
    reader = PdfReader(pdf_path)
    return (reader.pages[page_index].extract_text() or "").strip()


def render_page_as_image(pdf_path: str, page_index: int, dest_path: str, dpi: int = 200) -> None:
    """Renderiza uma página do PDF como PNG -- usado quando ela não tem
    texto nativo, pra seguir o mesmo caminho de foto (MaterialPage
    pendente de transcrição por leitura de imagem)."""
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_index]
        pix = page.get_pixmap(dpi=dpi)
        pix.save(dest_path)
    finally:
        doc.close()
