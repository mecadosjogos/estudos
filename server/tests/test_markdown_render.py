from app.markdown_render import normalize_list_indent, render_markdown


def test_sublista_com_2_espacos_fica_aninhada():
    md = (
        "- **Princípio da nacionalidade** — subdivide-se em dois:\n"
        "  - **Nacionalidade ativa** — sujeito ativo.\n"
        "  - **Nacionalidade passiva** — vítima.\n"
        "- **Princípio da competência universal**\n"
    )
    html = render_markdown(md)
    # a sublista abre dentro do item pai, e o item seguinte volta pra lista de fora
    assert html.count("<ul>") == 2
    antes, depois = html.split("Nacionalidade passiva")
    assert "<ul>" in antes.split("Princípio da nacionalidade")[1]
    assert depois.index("</ul>") < depois.index("competência universal")


def test_recuo_de_4_espacos_continua_igual():
    md = "- a\n    - b\n        - c\n- d\n"
    assert normalize_list_indent(md) == md


def test_tres_niveis_com_2_espacos():
    md = "- a\n  - b\n    - c\n  - b2\n- d\n"
    assert normalize_list_indent(md) == "- a\n    - b\n        - c\n    - b2\n- d\n"


def test_codigo_cercado_e_paragrafo_nao_mudam():
    md = "texto\n\n```\n  - nao mexe\n```\n\n1. um\n   continuação\n"
    out = normalize_list_indent(md)
    assert "  - nao mexe" in out
    assert "1. um\n    continuação" in out


def test_paragrafos_rotulados_viram_blocos():
    md = (
        "Explicação corrida.\n\n"
        "Definição: **Detração** é o desconto.\n\n"
        "**Material da aula:** \"texto da lousa\"\n\n"
        "Exemplo invertido: são dois casos:\n\n"
        "- caso um\n"
        "- caso dois\n\n"
        "Depois do exemplo."
    )
    html = render_markdown(md)
    assert '<p>Explicação corrida.</p>' in html
    assert 'guia-bloco--definicao' in html and '<strong>Detração</strong>' in html
    assert 'guia-bloco--material' in html
    exemplo = html.split('guia-bloco--exemplo')[1].split("</div>")[0]
    assert '<span class="guia-rotulo">Exemplo invertido</span>' in exemplo
    assert "caso dois" in exemplo
    assert "Depois do exemplo" not in exemplo


def test_rotulo_no_meio_do_paragrafo_ou_em_lista_nao_vira_bloco():
    html = render_markdown("texto\nExemplo: continua o parágrafo\n\n- Exemplo: item")
    assert "guia-bloco" not in html


def test_bloco_lei_e_falso_positivo():
    html = render_markdown('Lei: **art. 7º, I, "a", CP** — "contra a vida"\n\nLeia o artigo: depois.')
    assert html.count("guia-bloco--lei") == 1
    assert '<span class="guia-rotulo">Lei</span>' in html
