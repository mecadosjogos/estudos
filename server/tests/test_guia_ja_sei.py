""""Dominar o guia": o botão "↑ já sei, espaçar mais" vale dois "Lembrei"
seguidos -- sobe caixa e streak, grava as tentativas, e para se graduar."""

from test_guia_exercicios_filtro import _authed_client, _lesson_com_exercicios


def _progresso(session, exercicio_id):
    from sqlalchemy import select

    from app.models import GuiaExercicioProgresso

    session.expire_all()
    return session.scalar(select(GuiaExercicioProgresso).where(GuiaExercicioProgresso.exercicio_id == exercicio_id))


def _tentativas(session, exercicio_id):
    from sqlalchemy import func, select

    from app.models import GuiaExercicioTentativa

    return session.scalar(
        select(func.count(GuiaExercicioTentativa.id)).where(GuiaExercicioTentativa.exercicio_id == exercicio_id)
    )


def test_ja_sei_vale_dois_lembrei_e_mais_um_domina(app_env):
    from app.db import holder
    from app.models import GuiaExercicio

    client = _authed_client()
    with holder.SessionLocal() as session:
        lesson_id = _lesson_com_exercicios(session, ["definicao"] * 3)
        exercicio_id = session.query(GuiaExercicio.id).filter_by(lesson_id=lesson_id).first()[0]

    url = f"/lessons/{lesson_id}/guia/exercicios/{exercicio_id}"
    assert client.post(f"{url}/ajustar", data={"delta": 1}).status_code == 200

    with holder.SessionLocal() as session:
        progresso = _progresso(session, exercicio_id)
        # caixa 0 -> 1 (1º lembrei) -> 3 (2º emendado pula 2)
        assert (progresso.caixa, progresso.streak_atual, progresso.dominado_em) == (3, 2, None)
        assert _tentativas(session, exercicio_id) == 2

    client.post(f"{url}/responder", data={"shortcut": 2})
    with holder.SessionLocal() as session:
        progresso = _progresso(session, exercicio_id)
        assert progresso.dominado_em is not None
        assert progresso.na_mesa is False


def test_ja_sei_para_na_primeira_se_ja_graduar(app_env):
    from app.db import holder
    from app.models import GuiaExercicio

    client = _authed_client()
    with holder.SessionLocal() as session:
        lesson_id = _lesson_com_exercicios(session, ["definicao"] * 3)
        exercicio_id = session.query(GuiaExercicio.id).filter_by(lesson_id=lesson_id).first()[0]

    url = f"/lessons/{lesson_id}/guia/exercicios/{exercicio_id}"
    client.post(f"{url}/responder", data={"shortcut": 2})
    client.post(f"{url}/responder", data={"shortcut": 2})  # caixa 3, streak 2
    client.post(f"{url}/ajustar", data={"delta": 1})

    with holder.SessionLocal() as session:
        assert _progresso(session, exercicio_id).dominado_em is not None
        assert _tentativas(session, exercicio_id) == 3  # o 2º "lembrei" do botão não foi gravado


def test_dominei_gradua_na_hora_e_abre_vaga(app_env):
    from app.db import holder
    from app.models import GuiaExercicio

    client = _authed_client()
    with holder.SessionLocal() as session:
        lesson_id = _lesson_com_exercicios(session, ["definicao"] * 8)
        exercicio_id = session.query(GuiaExercicio.id).filter_by(lesson_id=lesson_id).first()[0]

    client.get(f"/lessons/{lesson_id}/guia/praticar")  # enche a mesa (5)
    assert client.post(f"/lessons/{lesson_id}/guia/exercicios/{exercicio_id}/dominei").status_code == 200

    with holder.SessionLocal() as session:
        progresso = _progresso(session, exercicio_id)
        # questão nova, caixa 0: um "Lembrei" só não graduaria -- o botão força
        assert progresso.dominado_em is not None
        assert (progresso.na_mesa, progresso.caixa, progresso.posicao_alvo) == (False, 5, None)
        assert _tentativas(session, exercicio_id) == 1

    html = client.get(f"/lessons/{lesson_id}/guia/praticar").text
    assert "1 dominado(s)" in html
    assert 'id="dominei-btn"' in html
    assert "quero ver de novo mais cedo" not in html
    # As respostas moram no rodapé fixo e começam apagadas (acendem ao revelar).
    rodape = html.split('id="praticar-rodape"', 1)[1].split("</nav>", 1)[0]
    assert rodape.count("data-apos-revelar disabled") == 4
    assert "/remover" in rodape


def test_mais_cedo_continua_so_reagendando(app_env):
    from app.db import holder
    from app.models import GuiaExercicio

    client = _authed_client()
    with holder.SessionLocal() as session:
        lesson_id = _lesson_com_exercicios(session, ["definicao"] * 3)
        exercicio_id = session.query(GuiaExercicio.id).filter_by(lesson_id=lesson_id).first()[0]

    client.get(f"/lessons/{lesson_id}/guia/praticar")  # enche a mesa
    client.post(f"/lessons/{lesson_id}/guia/exercicios/{exercicio_id}/ajustar", data={"delta": -1})
    with holder.SessionLocal() as session:
        assert _progresso(session, exercicio_id).caixa == 0
        assert _tentativas(session, exercicio_id) == 0


def test_estrelas_contam_quantos_lembrei_faltam(app_env):
    from sqlalchemy import select

    from app.db import holder
    from app.models import GuiaExercicio, GuiaExercicioProgresso, User
    from app.study.guia_scheduler import estrelas

    with holder.SessionLocal() as session:
        lesson_id = _lesson_com_exercicios(session, ["definicao"])
        exercicio = session.scalar(select(GuiaExercicio).where(GuiaExercicio.lesson_id == lesson_id))
        user_id = session.scalar(select(User.id))

        assert estrelas(session, exercicio, user_id) == 1  # sem progresso ainda: faltam 3

        progresso = GuiaExercicioProgresso(user_id=user_id, exercicio_id=exercicio.id)
        session.add(progresso)
        # (caixa, streak) -> estrelas: depois de 1 e de 2 "Lembrei" seguidos,
        # e caixa alta de antes sem sequência (o próximo já gradua).
        for caixa, streak, esperado in [(0, 0, 1), (1, 1, 2), (3, 2, 3), (4, 0, 3), (2, 0, 2)]:
            progresso.caixa, progresso.streak_atual = caixa, streak
            session.flush()
            assert estrelas(session, exercicio, user_id) == esperado, (caixa, streak)


def test_card_mostra_as_estrelas(app_env):
    from app.db import holder

    client = _authed_client()
    with holder.SessionLocal() as session:
        lesson_id = _lesson_com_exercicios(session, ["definicao"])

    html = client.get(f"/lessons/{lesson_id}/guia/praticar").text
    assert 'class="exercicio-estrelas"' in html
    assert html.count('class="cheia"') == 1 and html.count('class="vazia"') == 2
    assert "Faltam 3" in html
