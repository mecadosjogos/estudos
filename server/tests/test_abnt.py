from app.library.abnt import build_citation_with_page, build_reference
from app.models import Work


def _work(**kwargs):
    defaults = dict(titulo="Instituições de Direito Civil", tipo="livro")
    defaults.update(kwargs)
    return Work(**defaults)


def test_build_reference_single_author():
    work = _work(autores="Caio Mário da Silva Pereira", local="Rio de Janeiro", editora="Forense", ano=2020)
    ref = build_reference(work)
    assert ref.startswith("PEREIRA, Caio Mário da Silva.")
    assert "Instituições de Direito Civil." in ref
    assert "Rio de Janeiro: Forense, 2020." in ref


def test_build_reference_multiple_authors():
    work = _work(autores="Maria Silva; João Souza")
    ref = build_reference(work)
    assert ref.startswith("SILVA, Maria; SOUZA, João.")


def test_build_reference_with_subtitle_edition_and_volume():
    work = _work(subtitulo="parte geral", edicao="4. ed.", volume="1", autores="Ana Costa")
    ref = build_reference(work)
    assert "Instituições de Direito Civil: parte geral." in ref
    assert "4. ed." in ref
    assert "v. 1." in ref


def test_build_reference_organizador_without_autor():
    work = _work(organizadores="Pedro Lima", autores=None)
    ref = build_reference(work)
    assert ref.startswith("LIMA, Pedro (org.).")


def test_build_reference_translator():
    work = _work(autores="Hans Kelsen", tradutor="João Baptista Machado")
    ref = build_reference(work)
    assert "Tradução de João Baptista Machado." in ref


def test_referencia_manual_overrides_everything():
    work = _work(autores="Alguém", referencia_manual="MINHA REFERÊNCIA CUSTOMIZADA.")
    assert build_reference(work) == "MINHA REFERÊNCIA CUSTOMIZADA."


def test_build_citation_with_page_appends_page_number():
    work = _work(autores="Caio Mário", ano=2020)
    citation = build_citation_with_page(work, 247)
    assert citation.endswith("p. 247.")


def test_build_citation_without_page_omits_it():
    work = _work(autores="Caio Mário")
    citation = build_citation_with_page(work, None)
    assert "p." not in citation
