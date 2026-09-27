""""Dominar o guia": questão removida pelo admin some pra todos os usuários
(e o "desfazer" do admin a traz de volta pra todos); a de um usuário comum
continua só na fila dele."""

from starlette.testclient import TestClient

from test_guia_exercicios_filtro import _authed_client, _lesson_com_exercicios


def _cliente(username):
    from app.main import app

    client = TestClient(app)
    client.post("/login", data={"username": username, "senha": "x"})
    return client


def _preparar():
    from sqlalchemy import select

    from app.db import holder
    from app.models import GuiaExercicio, User
    from app.security import hash_password

    with holder.SessionLocal() as session:
        session.add(User(username="aluna", senha_hash=hash_password("x"), papel="usuario", status="aprovado"))
        lesson_id = _lesson_com_exercicios(session, ["definicao"] * 3)
        ids = list(session.scalars(select(GuiaExercicio.id).where(GuiaExercicio.lesson_id == lesson_id)))
        aluna_id = session.scalar(select(User.id).where(User.username == "aluna"))
        admin_id = session.scalar(select(User.id).where(User.username == "admin"))
        session.commit()
    return lesson_id, ids, aluna_id, admin_id


def _fila(user_id, lesson_id):
    """Ids que o usuário ainda vê na aula (pool) e o total contado."""
    from app.db import holder
    from app.models import Lesson
    from app.study.guia_scheduler import next_exercicio, pool_status, submit_attempt

    with holder.SessionLocal() as session:
        lesson = session.get(Lesson, lesson_id)
        vistos = set()
        for _ in range(12):
            exercicio = next_exercicio(session, lesson, user_id)
            if exercicio is None:
                break
            vistos.add(exercicio.id)
            submit_attempt(session, exercicio, user_id, resposta_texto=None, grau_acerto=0.0)
        return vistos, pool_status(session, lesson, user_id)["total"]


def test_admin_remove_para_todos_e_desfaz_para_todos(app_env):
    lesson_id, ids, aluna_id, admin_id = _preparar()
    aluna = _cliente("aluna")
    aluna.get(f"/lessons/{lesson_id}/guia/praticar")  # a questão entra na mesa dela antes

    admin = _authed_client()
    alvo = ids[0]
    admin.post(f"/lessons/{lesson_id}/guia/exercicios/{alvo}/remover")

    vistos, total = _fila(aluna_id, lesson_id)
    assert alvo not in vistos and total == 2
    assert f"exercicios/{alvo}/restaurar" in admin.get(f"/lessons/{lesson_id}/guia/praticar").text

    admin.post(f"/lessons/{lesson_id}/guia/exercicios/{alvo}/restaurar")
    vistos, total = _fila(aluna_id, lesson_id)
    assert alvo in vistos and total == 3


def test_usuario_comum_remove_so_da_propria_fila(app_env):
    lesson_id, ids, aluna_id, admin_id = _preparar()
    alvo = ids[1]
    _cliente("aluna").post(f"/lessons/{lesson_id}/guia/exercicios/{alvo}/remover")

    assert _fila(aluna_id, lesson_id)[1] == 2
    vistos, total = _fila(admin_id, lesson_id)
    assert alvo in vistos and total == 3
