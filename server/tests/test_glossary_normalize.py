from app.glossary.normalize import normalize_char_preserving


def test_strips_common_portuguese_accents():
    assert normalize_char_preserving("negócio jurídico") == "negocio juridico"


def test_strips_cedilla():
    assert normalize_char_preserving("boa-fé objetiva") == "boa-fe objetiva"


def test_lowercases():
    assert normalize_char_preserving("PRESCRIÇÃO") == "prescricao"


def test_length_is_always_preserved():
    for texto in ["negócio jurídico", "usucapião extraordinária", "art. 5º, § 2º", "café ☕ com açúcar"]:
        assert len(normalize_char_preserving(texto)) == len(texto)


def test_offsets_still_point_to_the_right_original_substring():
    texto = "A posse exige animus e usucapião."
    normalizado = normalize_char_preserving(texto)
    start = normalizado.index("usucapiao")
    end = start + len("usucapiao")
    # o mesmo span no texto ORIGINAL precisa ser a palavra com acento
    assert texto[start:end] == "usucapião"


def test_punctuation_and_digits_pass_through_unchanged():
    assert normalize_char_preserving("art. 1.238,") == "art. 1.238,"


def test_empty_string():
    assert normalize_char_preserving("") == ""
