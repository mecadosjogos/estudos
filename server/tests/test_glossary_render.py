import re

from app.glossary.matcher import VariantEntry
from app.glossary.normalize import normalize_char_preserving
from app.glossary.render import highlight_html


def _variant(display: str, term_id: int) -> VariantEntry:
    return VariantEntry(normalized=normalize_char_preserving(display), term_id=term_id, display=display)


def _strip_tags(html_out: str) -> str:
    return re.sub(r"<[^>]+>", "", html_out)


def test_wraps_a_plain_text_match():
    html_out = highlight_html("<p>A posse exige usucapião.</p>", [_variant("usucapião", 1)])
    assert '<span class="glossary-term" data-term-id="1">usucapião</span>' in html_out
    assert html_out.startswith("<p>")
    assert html_out.endswith("</p>")


def test_never_matches_inside_a_tag_attribute():
    """O termo "usucapião" aparece dentro de um atributo href -- não pode
    virar span ali, só no texto visível."""
    html_out = highlight_html(
        '<a href="/termos/usucapiao">Ver usucapião aqui</a>', [_variant("usucapião", 1)]
    )
    # o span só aparece uma vez, em volta do texto visível
    assert html_out.count("glossary-term") == 1
    assert 'href="/termos/usucapiao"' in html_out  # atributo intocado


def test_never_matches_inside_a_tag_name_or_structure():
    html_out = highlight_html("<div><span>usucapião</span></div>", [_variant("usucapião", 1)])
    assert "<div><span>" in html_out
    assert "</span></div>" in html_out.replace('<span class="glossary-term" data-term-id="1">usucapião</span>', "X")


def test_only_first_occurrence_per_call_is_wrapped():
    html_out = highlight_html(
        "<p>usucapião aparece aqui e usucapião aparece de novo.</p>", [_variant("usucapião", 1)]
    )
    assert html_out.count("glossary-term") == 1


def test_shared_seen_set_extends_across_multiple_calls():
    """Se o chamador quiser "primeira ocorrência da página", passa o
    mesmo set() entre blocos."""
    seen = set()
    first = highlight_html("<p>usucapião aqui.</p>", [_variant("usucapião", 1)], seen)
    second = highlight_html("<p>usucapião de novo.</p>", [_variant("usucapião", 1)], seen)
    assert "glossary-term" in first
    assert "glossary-term" not in second


def test_fresh_call_without_shared_set_highlights_each_block():
    """Sem compartilhar o set (o padrão -- "por bloco"), cada bloco marca
    sua própria primeira ocorrência."""
    first = highlight_html("<p>usucapião aqui.</p>", [_variant("usucapião", 1)])
    second = highlight_html("<p>usucapião de novo.</p>", [_variant("usucapião", 1)])
    assert "glossary-term" in first
    assert "glossary-term" in second


def test_escapes_html_special_characters_in_surrounding_text():
    html_out = highlight_html("<p>1 &lt; 2 e usucapião</p>", [_variant("usucapião", 1)])
    assert "1 &lt; 2" in html_out


def test_no_variants_returns_input_unchanged():
    original = "<p>Texto qualquer.</p>"
    assert highlight_html(original, []) == original


def test_visible_text_survives_stripped_of_tags():
    original_text = "A posse exige animus e usucapião de verdade."
    html_out = highlight_html(f"<p>{original_text}</p>", [_variant("usucapião", 1)])
    assert _strip_tags(html_out) == original_text


def test_multiple_terms_in_same_block_all_get_wrapped_once():
    html_out = highlight_html(
        "<p>Dolo eventual e culpa consciente são institutos diferentes.</p>",
        [_variant("dolo eventual", 1), _variant("culpa consciente", 2)],
    )
    assert 'data-term-id="1"' in html_out
    assert 'data-term-id="2"' in html_out
