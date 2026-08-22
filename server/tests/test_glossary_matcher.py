from app.glossary.matcher import VariantEntry, find_matches
from app.glossary.normalize import normalize_char_preserving


def _variant(display: str, term_id: int) -> VariantEntry:
    return VariantEntry(normalized=normalize_char_preserving(display), term_id=term_id, display=display)


def test_finds_simple_match_with_accent():
    texto = "A posse exige animus e usucapião."
    matches = find_matches(texto, [_variant("usucapião", 1)])
    assert len(matches) == 1
    m = matches[0]
    assert texto[m.start : m.end] == "usucapião"
    assert m.term_id == 1


def test_matches_case_insensitively():
    texto = "USUCAPIÃO extraordinária é diferente."
    matches = find_matches(texto, [_variant("usucapião", 1)])
    assert len(matches) == 1
    assert texto[matches[0].start : matches[0].end] == "USUCAPIÃO"


def test_matches_variant_without_accent_against_text_with_accent():
    """A variante cadastrada pode estar sem acento -- casa do mesmo jeito
    porque os dois lados são normalizados antes de comparar."""
    texto = "Isso é usucapião extraordinária."
    matches = find_matches(texto, [_variant("usucapiao", 1)])
    assert len(matches) == 1


def test_respects_word_boundaries():
    """"dolo" não deve casar dentro de "dolorosa"."""
    texto = "A situação foi dolorosa para todos, mas sem dolo evidente."
    matches = find_matches(texto, [_variant("dolo", 1)])
    assert len(matches) == 1
    assert texto[matches[0].start : matches[0].end] == "dolo"


def test_prefers_longer_variant_when_both_match_same_spot():
    texto = "Isso é boa-fé objetiva, não só boa-fé."
    matches = find_matches(texto, [_variant("boa-fé", 1), _variant("boa-fé objetiva", 2)])
    # a ocorrência "boa-fé objetiva" deve casar como termo 2 (mais específico)
    hits = [(texto[m.start : m.end], m.term_id) for m in matches]
    assert ("boa-fé objetiva", 2) in hits
    assert ("boa-fé", 1) in hits  # a segunda ocorrência, isolada, casa como termo 1


def test_no_overlap_between_matches():
    texto = "negócio jurídico e negócios jurídicos"
    matches = find_matches(texto, [_variant("negócio jurídico", 1), _variant("negócios jurídicos", 1)])
    spans = [(m.start, m.end) for m in matches]
    for i in range(len(spans) - 1):
        assert spans[i][1] <= spans[i + 1][0]


def test_multiple_terms_in_one_pass():
    texto = "Dolo eventual e culpa consciente são institutos diferentes."
    matches = find_matches(texto, [_variant("dolo eventual", 1), _variant("culpa consciente", 2)])
    hits = {(texto[m.start : m.end], m.term_id) for m in matches}
    assert ("Dolo eventual", 1) in hits
    assert ("culpa consciente", 2) in hits


def test_no_matches_returns_empty_list():
    assert find_matches("Texto qualquer sem termo nenhum.", [_variant("usucapião", 1)]) == []


def test_empty_variants_returns_empty_list():
    assert find_matches("Qualquer texto.", []) == []


def test_plural_variant_matches_only_plural_form():
    texto = "Vários negócios jurídicos foram citados, mas nenhum negócio jurídico específico."
    matches = find_matches(texto, [_variant("negócios jurídicos", 1)])
    assert len(matches) == 1
    assert texto[matches[0].start : matches[0].end] == "negócios jurídicos"
