from dataclasses import dataclass

from app.library.coverage import section_coverage


@dataclass
class FakeSection:
    id: int
    pagina_inicial: int
    pagina_final: int | None


@dataclass
class FakeMaterial:
    id: int
    titulo: str
    pagina_inicial: int | None
    pagina_final: int | None


def test_section_fully_covered():
    sections = [FakeSection(1, 1, 120)]
    materials = [FakeMaterial(1, "Cap 1-3", 1, 120)]
    result = section_coverage(sections, materials)
    assert result[0].coberto is True
    assert result[0].materiais == materials


def test_section_missing_entirely():
    sections = [FakeSection(1, 121, 240)]
    materials = [FakeMaterial(1, "Cap 1-3", 1, 120)]
    result = section_coverage(sections, materials)
    assert result[0].coberto is False
    assert result[0].materiais == []


def test_section_partially_covered_counts_as_covered():
    sections = [FakeSection(1, 100, 200)]
    materials = [FakeMaterial(1, "Metade", 150, 250)]
    result = section_coverage(sections, materials)
    assert result[0].coberto is True


def test_section_without_pagina_final_uses_pagina_inicial_as_point():
    sections = [FakeSection(1, 50, None)]
    materials = [FakeMaterial(1, "Cobre p.50", 40, 60)]
    result = section_coverage(sections, materials)
    assert result[0].coberto is True


def test_material_without_page_range_never_counts_as_coverage():
    """Material de ordem_manual (numeração desconhecida) não entra na
    conta -- não dá pra saber se ele cobre a seção ou não."""
    sections = [FakeSection(1, 1, 120)]
    materials = [FakeMaterial(1, "Ordem manual", None, None)]
    result = section_coverage(sections, materials)
    assert result[0].coberto is False
