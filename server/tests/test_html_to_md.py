from app.library.html_to_md import html_to_markdown


def test_preserves_headings():
    md = html_to_markdown("<h1>Usucapião</h1><p>Texto.</p>")
    assert "# Usucapião" in md


def test_preserves_bold():
    md = html_to_markdown("<p>O prazo é <b>quinze anos</b>.</p>")
    assert "**quinze anos**" in md


def test_preserves_lists():
    md = html_to_markdown("<ul><li>Posse</li><li>Justo título</li></ul>")
    assert "Posse" in md
    assert "Justo título" in md
    assert "*" in md or "-" in md


def test_strips_google_docs_wrapper_tags():
    html = '<html><body><p dir="ltr"><span>Texto simples</span></p></body></html>'
    md = html_to_markdown(html)
    assert md.strip() == "Texto simples"
