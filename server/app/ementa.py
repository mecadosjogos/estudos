"""Ementa oficial -- cadastro OPCIONAL que só enriquece o que os assuntos
emergidos das aulas já construíram (PLANO.md, fase 14): nunca um
pré-requisito. Importar (ou reimportar) substitui a LISTA de tópicos,
mas nunca rebaixa uma cobertura que já veio de aula -- casamento por
slug, mesmo padrão de `assuntos.py`."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .assuntos import ensure_cobertura, find_or_create_assunto
from .models import Ementa, EmentaTopico


def import_ementa(session: Session, subject_id: int, titulos: list[str]) -> Ementa:
    """Um tópico sem nenhuma aula que o cobre ainda vira um `Assunto` com
    cobertura `status="pendente"` -- "na ementa, mas ainda não dado". Um
    tópico que já tem cobertura (de aula) só ganha `ordem`; o título do
    `Assunto` já existente nunca é sobrescrito, pra não perder uma
    correção sua."""
    ementa = session.scalar(select(Ementa).where(Ementa.subject_id == subject_id))
    if ementa is None:
        ementa = Ementa(subject_id=subject_id)
        session.add(ementa)
        session.flush()
    else:
        for topico in list(ementa.topicos):
            session.delete(topico)
        session.flush()

    for ordem, titulo in enumerate(t.strip() for t in titulos if t.strip()):
        assunto = find_or_create_assunto(session, titulo)
        cobertura = ensure_cobertura(session, assunto.id, subject_id, origem="ementa", status="pendente")
        cobertura.ordem = ordem
        session.add(EmentaTopico(ementa_id=ementa.id, assunto_id=assunto.id, titulo=titulo, ordem=ordem))

    session.commit()
    return ementa
