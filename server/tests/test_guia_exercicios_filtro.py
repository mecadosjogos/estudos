""""Dominar o guia": filtro de tipos de exercício na tela de prática --
guardado por usuário+aula (GuiaLessonProgresso.tipos_desativados) e
aplicado em todas as portas da fila (mesa, backlog, próximo, contadores)."""

import json
from datetime import date


def _authed_client():
    from app.main import app

    from starlette.testclient import TestClient

    client = TestClient(app)
    client.post("/login", data={"username": "admin", "senha": "admin"})
    return client


def _lesson_com_exercicios(session, tipos):
    from sqlalchemy import select

    from app.models import GuiaExercicio, Lesson, Subject

    subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
    lesson = Lesson(subject_id=subject_id, titulo="Aula com guia", data=date(2026, 3, 12))
    lesson.guia_md = "# Guia\n\n## Seção\n\nCorpo."
    session.add(lesson)
    session.flush()
    for i, tipo in enumerate(tipos):
        session.add(
            GuiaExercicio(
                lesson_id=lesson.id,
                deriv_key=f"k{i}",
                tipo=tipo,
                secao_titulo="Seção",
                pergunta=f"Pergunta {i} ({tipo})",
                gabarito_json=json.dumps({"resposta": f"Resposta {i}"}),
                status="aceito",
            )
        )
    session.commit()
    return lesson.id


def test_filtro_restringe_fila_e_contadores(app_env):
    from sqlalchemy import select

    from app.db import holder
    from app.models import Lesson, User
    from app.study.guia_scheduler import next_exercicio, pool_status, set_tipos_filtro, tipos_ativos

    with holder.SessionLocal() as session:
        lesson_id = _lesson_com_exercicios(session, ["definicao"] * 3 + ["cloze"] * 2 + ["hierarquia"])
        user_id = session.scalar(select(User.id))
        lesson = session.get(Lesson, lesson_id)

        # sem filtro: todos os tipos valem
        assert tipos_ativos(session, lesson_id, user_id) >= {"definicao", "cloze", "hierarquia"}
        assert pool_status(session, lesson, user_id)["total"] == 6

        set_tipos_filtro(session, lesson, user_id, ["cloze"])

        pool = pool_status(session, lesson, user_id)
        assert pool["filtrado"] is True
        assert pool["total"] == 2  # só os dois cloze
        assert tipos_ativos(session, lesson_id, user_id) == {"cloze"}

        # a fila só entrega cloze, por mais que se avance
        for _ in range(5):
            exercicio = next_exercicio(session, lesson, user_id)
            assert exercicio is not None and exercicio.tipo == "cloze"


def test_filtro_expulsa_da_mesa_o_tipo_desligado(app_env):
    """Questão do tipo desligado não pode continuar ocupando vaga na mesa --
    senão a mesa fica menor que o tamanho alvo, com vagas invisíveis."""
    from sqlalchemy import select

    from app.db import holder
    from app.models import GuiaExercicio, GuiaExercicioProgresso, Lesson, User
    from app.study.guia_scheduler import ensure_mesa_filled, set_tipos_filtro

    with holder.SessionLocal() as session:
        lesson_id = _lesson_com_exercicios(session, ["definicao"] * 4 + ["cloze"] * 4)
        user_id = session.scalar(select(User.id))
        lesson = session.get(Lesson, lesson_id)

        ensure_mesa_filled(session, lesson, user_id)
        na_mesa = session.execute(
            select(GuiaExercicio.tipo)
            .join(GuiaExercicioProgresso, GuiaExercicioProgresso.exercicio_id == GuiaExercicio.id)
            .where(GuiaExercicioProgresso.user_id == user_id, GuiaExercicioProgresso.na_mesa.is_(True))
        ).all()
        assert {tipo for (tipo,) in na_mesa} == {"definicao", "cloze"}

        set_tipos_filtro(session, lesson, user_id, ["cloze"])

        na_mesa = session.execute(
            select(GuiaExercicio.tipo)
            .join(GuiaExercicioProgresso, GuiaExercicioProgresso.exercicio_id == GuiaExercicio.id)
            .where(GuiaExercicioProgresso.user_id == user_id, GuiaExercicioProgresso.na_mesa.is_(True))
        ).all()
        assert {tipo for (tipo,) in na_mesa} == {"cloze"}
        # as vagas abertas foram preenchidas pelo backlog do tipo que ficou
        assert len(na_mesa) == 4


def test_filtro_vazio_volta_a_valer_todos_os_tipos(app_env):
    from sqlalchemy import select

    from app.db import holder
    from app.models import Lesson, User
    from app.study.guia_scheduler import pool_status, set_tipos_filtro

    with holder.SessionLocal() as session:
        lesson_id = _lesson_com_exercicios(session, ["definicao", "cloze", "hierarquia"])
        user_id = session.scalar(select(User.id))
        lesson = session.get(Lesson, lesson_id)

        set_tipos_filtro(session, lesson, user_id, ["cloze"])
        assert pool_status(session, lesson, user_id)["total"] == 1

        set_tipos_filtro(session, lesson, user_id, [])  # nada marcado = sem filtro
        pool = pool_status(session, lesson, user_id)
        assert pool["filtrado"] is False
        assert pool["total"] == 3


def test_rota_de_filtro_e_tela_de_pratica(app_env):
    from sqlalchemy import select

    from app.db import holder
    from app.models import GuiaLessonProgresso, User

    with holder.SessionLocal() as session:
        lesson_id = _lesson_com_exercicios(session, ["definicao", "cloze", "aplicacao_caso"])

    client = _authed_client()
    pagina = client.get(f"/lessons/{lesson_id}/guia/praticar")
    assert pagina.status_code == 200
    assert "Filtrar por tipo de exercício" in pagina.text
    assert "Aplicação de caso" in pagina.text

    resposta = client.post(f"/lessons/{lesson_id}/guia/tipos-filtro", data={"tipos": ["cloze"]}, follow_redirects=False)
    assert resposta.status_code == 303

    with holder.SessionLocal() as session:
        user_id = session.scalar(select(User.id))
        progresso = session.scalar(
            select(GuiaLessonProgresso).where(
                GuiaLessonProgresso.user_id == user_id, GuiaLessonProgresso.lesson_id == lesson_id
            )
        )
        desativados = json.loads(progresso.tipos_desativados)
        assert "cloze" not in desativados
        assert "definicao" in desativados

    pagina = client.get(f"/lessons/{lesson_id}/guia/praticar")
    assert "filtro ativo" in pagina.text
    assert "(cloze)" in pagina.text  # a pergunta que restou é a do tipo marcado
