from shared.text import markdown_para_narracao


def test_strips_headers_of_any_depth():
    texto = markdown_para_narracao("## Seção\n### Sub\n#### Sub-sub\nconteúdo")
    assert "#" not in texto
    assert "Seção" in texto and "Sub" in texto and "conteúdo" in texto


def test_strips_bold_and_italic_markers():
    texto = markdown_para_narracao("**Art. 1º**: a *posse* é o exercício de fato.")
    assert "*" not in texto
    assert "Art. 1º" in texto
    assert "posse" in texto


def test_strips_bullet_and_numbered_list_markers():
    texto = markdown_para_narracao("- primeiro item\n- segundo item\n1. terceiro item")
    assert "- " not in texto
    assert "1." not in texto
    assert "primeiro item" in texto and "segundo item" in texto and "terceiro item" in texto


def test_keeps_link_text_and_drops_url():
    texto = markdown_para_narracao("Ver [CF/88](https://example.com/cf) sobre o tema.")
    assert "https://example.com/cf" not in texto
    assert "[" not in texto and "](" not in texto
    assert "CF/88" in texto


def test_strips_blockquote_and_horizontal_rule():
    texto = markdown_para_narracao("> citação\n---\ntexto normal")
    assert ">" not in texto
    assert "---" not in texto
    assert "citação" in texto and "texto normal" in texto


def test_drops_fenced_code_blocks():
    texto = markdown_para_narracao("antes\n```mermaid\nA --> B\n```\ndepois")
    assert "-->" not in texto
    assert "```" not in texto
    assert "antes" in texto and "depois" in texto


def test_does_not_touch_plain_prose_with_parentheses_and_periods():
    texto = markdown_para_narracao("O Código Civil de 2002 (Lei 10.406).")
    assert texto == "O Código Civil de 2002 (Lei 10.406)."


def test_blank_line_becomes_sentence_pause_not_missing_space():
    texto = markdown_para_narracao("primeira frase\n\nsegunda frase")
    assert texto == "primeira frase. segunda frase"
