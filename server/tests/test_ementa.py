from sqlalchemy import select

from app.assuntos import ensure_cobertura, find_or_create_assunto
from app.ementa import import_ementa
from app.models import Assunto, AssuntoCobertura, Ementa, EmentaTopico


def _subject_id(session, sigla="TGDC"):
    from app.models import Subject

    return session.scalar(select(Subject.id).where(Subject.sigla == sigla))


def test_import_ementa_creates_topics_in_order(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)
        ementa = import_ementa(session, subject_id, ["Pessoa natural", "Capacidade", "Domicílio"])
        session.commit()

        topicos = session.scalars(
            select(EmentaTopico).where(EmentaTopico.ementa_id == ementa.id).order_by(EmentaTopico.ordem)
        ).all()
        assert [t.titulo for t in topicos] == ["Pessoa natural", "Capacidade", "Domicílio"]
        assert [t.ordem for t in topicos] == [0, 1, 2]


def test_import_ementa_creates_pending_coverage_for_untaught_topics(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)
        import_ementa(session, subject_id, ["Usucapião"])
        session.commit()

        assunto = session.scalar(select(Assunto).where(Assunto.slug == "usucapiao"))
        cobertura = session.scalar(
            select(AssuntoCobertura).where(
                AssuntoCobertura.assunto_id == assunto.id, AssuntoCobertura.subject_id == subject_id
            )
        )
        assert cobertura.status == "pendente"
        assert cobertura.origem == "ementa"


def test_import_ementa_never_downgrades_existing_coverage_from_lesson(app_env):
    """Um tópico que a aula já cobriu não pode virar "pendente" só porque
    a ementa também menciona ele (PLANO.md: "enriquece... sem
    substituir")."""
    from app.db import holder

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)
        assunto = find_or_create_assunto(session, "Posse")
        ensure_cobertura(session, assunto.id, subject_id, origem="ia")
        session.commit()

        import_ementa(session, subject_id, ["Posse"])
        session.commit()

        cobertura = session.scalar(
            select(AssuntoCobertura).where(
                AssuntoCobertura.assunto_id == assunto.id, AssuntoCobertura.subject_id == subject_id
            )
        )
        assert cobertura.status == "dado"
        assert cobertura.origem == "ia"
        assert cobertura.ordem == 0


def test_import_ementa_never_renames_existing_assunto(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)
        assunto = find_or_create_assunto(session, "Posse")
        assunto.titulo = "Posse (renomeado por mim)"
        session.commit()

        import_ementa(session, subject_id, ["Posse"])
        session.commit()

        refreshed = session.get(Assunto, assunto.id)
        assert refreshed.titulo == "Posse (renomeado por mim)"


def test_ensure_cobertura_upgrades_pending_to_dado_when_lesson_confirms_it(app_env):
    """Um tópico só na ementa ("pendente") precisa virar "dado" assim que
    uma aula de verdade confirma o assunto -- senão fica "pendente" pra
    sempre mesmo depois de dado (achado testando a fase 14 contra o
    staging real)."""
    from app.db import holder

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)
        import_ementa(session, subject_id, ["Posse"])
        session.commit()

        assunto = session.scalar(select(Assunto).where(Assunto.slug == "posse"))
        antes = session.scalar(
            select(AssuntoCobertura).where(
                AssuntoCobertura.assunto_id == assunto.id, AssuntoCobertura.subject_id == subject_id
            )
        )
        assert antes.status == "pendente"

        ensure_cobertura(session, assunto.id, subject_id, origem="ia")  # mesma chamada de accept_lesson_assunto
        session.commit()

        depois = session.scalar(
            select(AssuntoCobertura).where(
                AssuntoCobertura.assunto_id == assunto.id, AssuntoCobertura.subject_id == subject_id
            )
        )
        assert depois.status == "dado"


def test_reimport_ementa_replaces_topic_list(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        subject_id = _subject_id(session)
        ementa = import_ementa(session, subject_id, ["Posse", "Propriedade"])
        session.commit()
        ementa_id = ementa.id

        import_ementa(session, subject_id, ["Só isso"])
        session.commit()

        topicos = session.scalars(select(EmentaTopico).where(EmentaTopico.ementa_id == ementa_id)).all()
        assert [t.titulo for t in topicos] == ["Só isso"]

        # a ementa continua sendo a mesma linha (uma por matéria), não duplicou
        ementas = session.scalars(select(Ementa).where(Ementa.subject_id == subject_id)).all()
        assert len(ementas) == 1
