import fitz
import pytest

from app.library.pdf import extract_native_text, has_native_text, page_count, render_page_as_image


def _make_text_pdf(path, pages_text: list[str]):
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


def _make_scanned_pdf(path):
    """Simula uma página escaneada: uma imagem cobrindo a página, sem
    nenhum texto extraível."""
    doc = fitz.open()
    page = doc.new_page()
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100), False)
    pixmap.set_rect(pixmap.irect, (255, 255, 255))
    page.insert_image(page.rect, pixmap=pixmap)
    doc.save(str(path))
    doc.close()


@pytest.fixture()
def text_pdf(tmp_path):
    path = tmp_path / "texto.pdf"
    _make_text_pdf(path, ["Primeira página com bastante texto extraível de verdade.", "Segunda página também com texto."])
    return str(path)


@pytest.fixture()
def scanned_pdf(tmp_path):
    path = tmp_path / "escaneado.pdf"
    _make_scanned_pdf(path)
    return str(path)


def test_page_count(text_pdf):
    assert page_count(text_pdf) == 2


def test_has_native_text_true_for_text_pdf(text_pdf):
    assert has_native_text(text_pdf) == [True, True]


def test_has_native_text_false_for_scanned_pdf(scanned_pdf):
    assert has_native_text(scanned_pdf) == [False]


def test_extract_native_text_returns_page_content(text_pdf):
    text = extract_native_text(text_pdf, 0)
    assert "Primeira página" in text


def test_render_page_as_image_creates_file(scanned_pdf, tmp_path):
    dest = tmp_path / "pagina1.png"
    render_page_as_image(scanned_pdf, 0, str(dest))
    assert dest.exists()
    assert dest.stat().st_size > 0
