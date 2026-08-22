import re

from app.study.cloze import render_cloze_html, select_blanks


def test_select_blanks_ignores_stopwords_and_short_words():
    blanks = select_blanks("O réu agiu com dolo eventual, assumindo o risco do resultado.")
    words = {b["palavra"].lower() for b in blanks}
    assert "com" not in words
    assert "do" not in words
    assert "o" not in words


def test_select_blanks_picks_significant_legal_terms():
    blanks = select_blanks("A usucapião extraordinária exige posse mansa e pacífica.")
    words = {b["palavra"].lower() for b in blanks}
    assert "usucapião" in words or "extraordinária" in words


def test_select_blanks_caps_at_max_blanks():
    texto = "Usucapião extraordinária exige posse mansa pacífica ininterrupta quinze anos justo título"
    blanks = select_blanks(texto, max_blanks=3)
    assert len(blanks) <= 3


def test_select_blanks_never_covers_whole_short_text():
    blanks = select_blanks("Isso é assim, então tá bom.")
    assert blanks == []


def test_select_blanks_returns_in_text_order():
    texto = "Prescrição extingue pretensão; decadência extingue direito potestativo."
    blanks = select_blanks(texto, max_blanks=3)
    starts = [b["start"] for b in blanks]
    assert starts == sorted(starts)


def test_render_cloze_html_wraps_only_chosen_words():
    texto = "A posse exige corpus e animus."
    blanks = select_blanks(texto, max_blanks=2)
    html_out = render_cloze_html(texto, blanks)

    for b in blanks:
        assert f'data-answer="{b["palavra"]}"' in html_out

    stripped = re.sub(r"<[^>]+>", "", html_out)
    assert stripped == texto


def test_render_cloze_html_escapes_special_characters():
    texto = "O <réu> alega \"boa-fé\" & confiança."
    html_out = render_cloze_html(texto, select_blanks(texto))
    assert "<réu>" not in html_out
    assert "&lt;réu&gt;" in html_out


def test_render_cloze_html_no_blanks_returns_escaped_text_unchanged():
    texto = "Texto curto e simples."
    html_out = render_cloze_html(texto, [])
    assert html_out == texto  # nada pra escapar aqui, sem span nenhum
    assert "<span" not in html_out
