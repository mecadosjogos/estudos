"""Assunto -- global, atravessa materias e semestres (PLANO.md, fase 8).

Nasce com as mesmas ferramentas do glossario porque vai errar do mesmo
jeito: a IA propõe "Capacidade" numa aula e "Capacidade de Fato" noutra,
achando que são coisas diferentes -- sem fundir/renomear/separar desde o
início, em dois meses são 60 assuntos quase-iguais."""

import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Assunto, AssuntoCobertura, LessonAssunto


def normalize_slug(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    ascii_text = nfkd.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug or "assunto"


def find_or_create_assunto(session: Session, titulo: str) -> Assunto:
    """Casamento por slug -- é o que impede duas grafias do mesmo assunto
    virarem dois registros (mesmo padrão do glossário)."""
    slug = normalize_slug(titulo)
    existing = session.scalar(select(Assunto).where(Assunto.slug == slug))
    if existing is not None:
        return existing
    assunto = Assunto(slug=slug, titulo=titulo.strip())
    session.add(assunto)
    session.flush()
    return assunto


def ensure_cobertura(session: Session, assunto_id: int, subject_id: int, origem: str = "ia") -> AssuntoCobertura:
    existing = session.scalar(
        select(AssuntoCobertura).where(
            AssuntoCobertura.assunto_id == assunto_id, AssuntoCobertura.subject_id == subject_id
        )
    )
    if existing is not None:
        return existing
    cobertura = AssuntoCobertura(assunto_id=assunto_id, subject_id=subject_id, origem=origem)
    session.add(cobertura)
    session.flush()
    return cobertura


def merge_assuntos(session: Session, source_id: int, target_id: int) -> None:
    """Migra vínculos e coberturas de source pra target e apaga source --
    nada fica órfão (PLANO.md: 'fundir dois termos quase-duplicados e
    confirmar que tudo migrou')."""
    if source_id == target_id:
        return

    for link in session.scalars(select(LessonAssunto).where(LessonAssunto.assunto_id == source_id)):
        link.assunto_id = target_id

    target_subjects = {
        row.subject_id
        for row in session.scalars(select(AssuntoCobertura).where(AssuntoCobertura.assunto_id == target_id))
    }
    for cobertura in session.scalars(select(AssuntoCobertura).where(AssuntoCobertura.assunto_id == source_id)):
        if cobertura.subject_id in target_subjects:
            session.delete(cobertura)
        else:
            cobertura.assunto_id = target_id

    source = session.get(Assunto, source_id)
    session.delete(source)
    session.flush()
