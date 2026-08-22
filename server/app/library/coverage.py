"""Mapa de cobertura da obra (PLANO.md, "O sumário fotografado vira o
esqueleto da obra"): compara os intervalos de página de cada seção contra
os materiais já subidos, pra mostrar o que você tem e o que falta. Nada
disso é guardado -- sempre recalculado na hora, porque materiais entram e
saem sem aviso prévio.
"""

from dataclasses import dataclass


@dataclass
class SectionCoverage:
    section: "object"
    coberto: bool
    materiais: list


def section_coverage(sections: list, materials: list) -> list[SectionCoverage]:
    result = []
    for section in sections:
        fim = section.pagina_final if section.pagina_final is not None else section.pagina_inicial
        cobrindo = [
            m
            for m in materials
            if m.pagina_inicial is not None
            and m.pagina_final is not None
            and m.pagina_inicial <= fim
            and m.pagina_final >= section.pagina_inicial
        ]
        result.append(SectionCoverage(section=section, coberto=bool(cobrindo), materiais=cobrindo))
    return result
