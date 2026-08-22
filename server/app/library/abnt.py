"""Referência ABNT de uma obra (PLANO.md, "Biblioteca"). Cobre o caso comum
(um ou mais autores, edição, local, editora, ano) — os casos que a montagem
automática erra de propósito (coletânea com organizador, tradução, e-book,
volume de série) têm `Work.referencia_manual` como escape hatch: preenchido,
ele é o que `build_reference` devolve, ignorando tudo abaixo.
"""

from .. import models


def _autor_sobrenome_primeiro(nome: str) -> str:
    """"João da Silva" -> "SILVA, João da" -- só o último nome vira
    sobrenome; não tenta acertar partículas (de/da/dos) nem sobrenomes
    compostos, que é exatamente o tipo de caso em que o campo de
    referência manual existe para você corrigir."""
    partes = nome.strip().split()
    if len(partes) < 2:
        return nome.strip().upper()
    sobrenome = partes[-1]
    resto = " ".join(partes[:-1])
    return f"{sobrenome.upper()}, {resto}"


def _formatar_autores(autores: str) -> str:
    nomes = [n.strip() for n in autores.split(";") if n.strip()]
    if not nomes:
        return ""
    return "; ".join(_autor_sobrenome_primeiro(n) for n in nomes)


def build_reference(work: "models.Work") -> str:
    """Monta a referência ABNT a partir dos campos da obra. Chame só
    quando `work.referencia_manual` estiver vazio -- ele sempre tem
    prioridade (PLANO.md: "sobrepõe a ABNT automática")."""
    if work.referencia_manual and work.referencia_manual.strip():
        return work.referencia_manual.strip()

    partes: list[str] = []

    if work.autores:
        partes.append(_formatar_autores(work.autores) + ".")
    elif work.organizadores:
        partes.append(_formatar_autores(work.organizadores) + " (org.).")

    titulo = work.titulo.strip()
    if work.subtitulo:
        titulo += f": {work.subtitulo.strip()}"
    partes.append(f"{titulo}.")

    if work.autores and work.organizadores:
        partes.append(f"Organização de {work.organizadores}.")
    if work.tradutor:
        partes.append(f"Tradução de {work.tradutor}.")
    if work.edicao:
        partes.append(f"{work.edicao}.")
    if work.volume:
        partes.append(f"v. {work.volume}.")
    if work.tomo:
        partes.append(f"t. {work.tomo}.")

    rodape = ""
    if work.local:
        rodape += work.local
    if work.editora:
        rodape += (": " if rodape else "") + work.editora
    if work.ano:
        rodape += (", " if rodape else "") + str(work.ano)
    if rodape:
        partes.append(rodape + ".")

    return " ".join(partes)


def build_citation_with_page(work: "models.Work", pagina: int | None) -> str:
    """A mesma referência, com ", p. N" no final -- o que o botão "copiar
    citação" da busca e da leitura do material devolve."""
    referencia = build_reference(work)
    if pagina is None:
        return referencia
    return f"{referencia} p. {pagina}."
