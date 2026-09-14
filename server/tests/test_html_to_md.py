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


def test_google_docs_flat_lists_keep_visual_indentation():
    # Export do Docs: níveis como <ul> irmãos, recuo só no CSS por classe.
    html = (
        "<html><head><style>.c8{margin-left:36pt}.c5{margin-left:72pt}"
        ".c0{margin-left:108pt}.c11{text-indent:36pt}</style></head>"
        '<body class="doc-content"><p class="c7">Fontes</p>'
        '<p class="c11">recuado</p>'
        '<ul class="lst-kix_abc-0 start"><li class="c8">Common Law</li></ul>'
        '<ul class="lst-kix_abc-1 start"><li class="c5">súmulas</li></ul>'
        '<ul class="lst-kix_abc-2 start"><li class="c0">vinculante</li></ul>'
        "</body></html>"
    )
    assert html_to_markdown(html).splitlines() == [
        "Fontes",
        "    recuado",
        "* Common Law",
        "    * súmulas",
        "        * vinculante",
    ]
