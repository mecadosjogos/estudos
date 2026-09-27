from shared.text import markdown_para_narracao


def test_strips_headers_of_any_depth():
    texto = markdown_para_narracao("## Seção\n### Sub\n#### Sub-sub\nconteúdo")
    assert "#" not in texto
    assert "Seção" in texto and "Sub" in texto and "conteúdo" in texto


def test_strips_bold_and_italic_markers():
    texto = markdown_para_narracao("**Art. 1º**: a *posse* é o exercício de fato.")
    assert "*" not in texto
    assert "artigo 1º" in texto
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
    assert "CF 88" in texto


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


def test_table_reads_cells_without_pipes_or_separator():
    texto = markdown_para_narracao("| Espécie | Princípio |\n|---|:---:|\n| **Alínea a** | Defesa |")
    assert texto == "Espécie, Princípio. Alínea a, Defesa"


def test_marcador_de_trecho_inaudivel_vira_aviso_curto():
    texto = markdown_para_narracao("foi banido por [trecho incompleto/inaudível na transcrição]. Cumprindo sanção")
    assert texto == "foi banido por, trecho inaudível. Cumprindo sanção"


def test_titulo_dentro_de_citacao_perde_o_cerquilha():
    texto = markdown_para_narracao("**Material da aula:**\n\n> # Direito Romano\n> ## Periodo Arcaico")
    assert texto == "Material da aula. Direito Romano. Periodo Arcaico"


def test_italico_dentro_de_negrito_some_por_inteiro():
    texto = markdown_para_narracao("Atenção: **quando eu disser *sempre* ou *nunca*, anotem**.")
    assert texto == "Atenção: quando eu disser sempre ou nunca, anotem."


def test_item_de_lista_com_ponto_e_virgula_nao_dobra_pontuacao():
    texto = markdown_para_narracao("- uma punição severa;\n- a **morte**..")
    assert texto == "uma punição severa. a morte."


def test_simbolos_viram_palavra_ou_pausa():
    from shared.text import texto_para_fala

    assert texto_para_fala("em 99,9% das vezes") == "em 99,9 por cento das vezes"
    assert texto_para_fala('"não há crime sem lei" = reserva legal') == "não há crime sem lei é reserva legal"
    assert texto_para_fala("legalidade = lacuna + lacuna .") == "legalidade é lacuna mais lacuna."
    assert texto_para_fala("cumpriu a pena — a lei nova; voo São Paulo–Paris") == (
        "cumpriu a pena, a lei nova; voo São Paulo, Paris"
    )
    assert texto_para_fala("comercial [...] lacuna […]") == "comercial lacuna"
    assert texto_para_fala("Conceito · Objeto · Relação") == "Conceito, Objeto, Relação"
    assert texto_para_fala("rock'n'roll e 'interesse específico'") == "rock'n'roll e interesse específico"
    assert texto_para_fala("incompleto/inaudível, e/ou, art. 5º, § 1º") == (
        "incompleto ou inaudível, e ou, artigo 5º, parágrafo 1º"
    )


def test_quebra_de_linha_do_windows_vira_pausa_simples():
    texto = markdown_para_narracao("Primeiro parágrafo.\r\n\r\n- item;\r\n- outro\r\n")
    assert texto == "Primeiro parágrafo. item. outro."
