from app.ai.guia_parser import TITULO_FALLBACK, parse_guia_markdown


def test_subtitulos_de_qualquer_profundidade_nao_viram_secao_nova():
    """A IA agora pode ir além de um nível de sub-título (###, ####, ...)
    quando a hierarquia do professor pedir -- só o "## " de nível único
    delimita seção nova; qualquer profundidade abaixo disso fica dentro
    do corpo da seção, sem numeração."""
    guia_md = """# Aula

## Classificação

### Nível 2

#### Nível 3

##### Nível 4

Texto final.
"""
    parsed = parse_guia_markdown(guia_md)
    assert [s.titulo for s in parsed.secoes] == ["Classificação"]
    corpo = parsed.secoes[0].corpo
    assert "### Nível 2" in corpo
    assert "#### Nível 3" in corpo
    assert "##### Nível 4" in corpo
    assert "Texto final." in corpo


def test_full_document_with_arvore_sumario_secoes_e_trechos():
    guia_md = """# Posse e propriedade

## Árvore de conhecimento

- Posse
  - Direta
  - Indireta
- Propriedade

## Sumário dos tópicos abordados

- Introdução
- Corpus e animus

## Introdução

Texto da introdução.

## Corpus e animus

A posse exige **corpus** e **animus**.

### Exemplo

Uma pessoa que mora numa casa tem corpus e animus.

## Trechos incompletos/inaudíveis

- [trecho incompleto/inaudível na transcrição] o que ele disse sobre detenção
"""
    parsed = parse_guia_markdown(guia_md)

    assert parsed.titulo == "Posse e propriedade"

    assert [n.rotulo for n in parsed.arvore] == ["Posse", "Propriedade"]
    assert [n.rotulo for n in parsed.arvore[0].filhos] == ["Direta", "Indireta"]
    assert parsed.arvore[1].filhos == []

    assert [t.titulo for t in parsed.topicos] == ["Introdução", "Corpus e animus"]

    assert [s.titulo for s in parsed.secoes] == ["Introdução", "Corpus e animus"]
    assert parsed.secoes[0].corpo == "Texto da introdução."
    # Sub-título "###" dentro do corpo da seção não vira uma seção nova.
    assert "### Exemplo" in parsed.secoes[1].corpo
    assert "Uma pessoa que mora numa casa" in parsed.secoes[1].corpo

    assert parsed.trechos_incompletos == [
        "[trecho incompleto/inaudível na transcrição] o que ele disse sobre detenção"
    ]


def test_arvore_ausente_fica_vazia():
    guia_md = """# Aula

## Sumário dos tópicos abordados

- Posse

## Posse

Conteúdo.
"""
    parsed = parse_guia_markdown(guia_md)
    assert parsed.arvore == []
    assert [s.titulo for s in parsed.secoes] == ["Posse"]


def test_titulo_ausente_cai_no_fallback():
    guia_md = """## Posse

Conteúdo sem linha de título.
"""
    parsed = parse_guia_markdown(guia_md)
    assert parsed.titulo == TITULO_FALLBACK
    assert [s.titulo for s in parsed.secoes] == ["Posse"]


def test_sem_nenhum_cabecalho_cai_em_secao_unica_sem_perder_conteudo():
    guia_md = "# Aula\n\nSó um parágrafo corrido, sem nenhum '## ' no meio."
    parsed = parse_guia_markdown(guia_md)

    assert len(parsed.secoes) == 1
    assert parsed.secoes[0].titulo == "Aula"
    assert "Só um parágrafo corrido" in parsed.secoes[0].corpo
    # Sem sumário explícito -- cai no default 1:1 com as seções.
    assert [t.titulo for t in parsed.topicos] == ["Aula"]


def test_ia_numera_cabecalho_mesmo_assim_numero_e_removido():
    guia_md = """# Aula

## 1. Introdução

Texto.

## 2) Posse

Outro texto.
"""
    parsed = parse_guia_markdown(guia_md)
    assert [s.titulo for s in parsed.secoes] == ["Introdução", "Posse"]


def test_cabecalhos_acentuados_sao_reconhecidos():
    guia_md = """# Aula

## Árvore de conhecimento

- Posse

## Sumário dos tópicos abordados

- Posse

## Posse

Conteúdo.
"""
    parsed = parse_guia_markdown(guia_md)
    assert [n.rotulo for n in parsed.arvore] == ["Posse"]
    assert [t.titulo for t in parsed.topicos] == ["Posse"]


def test_sem_sumario_explicito_topicos_ficam_1_para_1_com_secoes():
    guia_md = """# Aula

## Introdução

Texto 1.

## Posse

Texto 2.
"""
    parsed = parse_guia_markdown(guia_md)
    assert [t.titulo for t in parsed.topicos] == ["Introdução", "Posse"]


def test_string_vazia_nao_lanca():
    parsed = parse_guia_markdown("")
    assert parsed.titulo == TITULO_FALLBACK
    assert parsed.secoes == []
    assert parsed.topicos == []
    assert parsed.arvore == []
    assert parsed.trechos_incompletos == []
