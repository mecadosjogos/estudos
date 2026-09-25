"""Fila da IA local (PLANO.md, fase 13b): long-poll, claim, heartbeat,
job parado voltando pra fila, resultado idempotente, presença."""

import threading
import time
from datetime import datetime, timedelta, timezone

from starlette.testclient import TestClient

MAQUINA = {"Authorization": "Bearer test-token"}


def _client():
    from app.main import app

    return TestClient(app)


def _authed_client():
    client = _client()
    client.post("/login", data={"username": "admin", "senha": "admin"})
    return client


def _job(session, tipo="dissertativa_gerar"):
    from app.ai import fila_local

    return fila_local.criar_job(
        session, tipo=tipo,
        chamadas=[{"id": "questao", "rotulo": "criando", "sistema": "s", "prompt": "p", "schema": {}, "temperatura": 0.7, "max_tokens": 10}],
    )


def test_maquina_sem_token_recebe_401(app_env):
    resp = _client().get("/api/ia-local/next", params={"worker_name": "pc"})
    assert resp.status_code == 401


def test_next_sem_job_espera_e_devolve_vazio(app_env):
    inicio = time.monotonic()
    resp = _client().get("/api/ia-local/next", params={"worker_name": "pc", "wait": 0.5}, headers=MAQUINA)
    assert resp.status_code == 200
    assert resp.json() == {"job": None}
    assert time.monotonic() - inicio >= 0.4


def test_next_reivindica_job_e_so_uma_vez(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        job_id = _job(session).id

    client = _client()
    primeiro = client.get("/api/ia-local/next", params={"worker_name": "pc"}, headers=MAQUINA).json()["job"]
    assert primeiro["id"] == job_id
    assert primeiro["chamadas"][0]["id"] == "questao"
    assert "meta" not in primeiro  # meta é só do servidor
    assert client.get("/api/ia-local/next", params={"worker_name": "pc"}, headers=MAQUINA).json() == {"job": None}


def test_long_poll_acorda_na_hora_quando_um_job_chega(app_env):
    """O ponto do long-poll: a máquina recebe o job em ~instantes, não no
    próximo ciclo de polling."""
    from app.db import holder

    resultado = {}

    def maquina_esperando():
        inicio = time.monotonic()
        resp = _client().get("/api/ia-local/next", params={"worker_name": "pc", "wait": 10}, headers=MAQUINA)
        resultado["job"] = resp.json()["job"]
        resultado["segundos"] = time.monotonic() - inicio

    t = threading.Thread(target=maquina_esperando)
    t.start()
    time.sleep(0.8)
    with holder.SessionLocal() as session:
        job_id = _job(session).id
    t.join(timeout=10)

    assert resultado["job"]["id"] == job_id
    # Chegou bem antes dos 10 s de espera -- acordou pelo evento/reconsulta.
    assert resultado["segundos"] < 4


def test_next_registra_presenca_e_navegador_ve_maquina_ligada(app_env):
    client = _authed_client()
    assert client.get("/ia-local/status.json").json() == {"online": False}

    _client().get(
        "/api/ia-local/next", params={"worker_name": "pc", "motor": "local", "modelo": "qwen3.5-4b"}, headers=MAQUINA
    )
    status = client.get("/ia-local/status.json").json()
    assert status["online"] is True
    assert status["modelo"] == "qwen3.5-4b"


def test_presenca_antiga_conta_como_desligada(app_env):
    from app.db import holder
    from app.models import IaLocalPresenca

    with holder.SessionLocal() as session:
        session.add(IaLocalPresenca(worker_name="pc", visto_em=datetime.now(timezone.utc) - timedelta(minutes=5)))
        session.commit()
    assert _authed_client().get("/ia-local/status.json").json() == {"online": False}


def test_job_sem_heartbeat_volta_pra_fila(app_env):
    from app.db import holder
    from app.models import IaLocalJob

    with holder.SessionLocal() as session:
        job_id = _job(session).id

    client = _client()
    primeiro = client.get("/api/ia-local/next", params={"worker_name": "pc"}, headers=MAQUINA).json()["job"]
    with holder.SessionLocal() as session:
        job = session.get(IaLocalJob, job_id)
        job.heartbeat_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        session.commit()

    segundo = client.get("/api/ia-local/next", params={"worker_name": "notebook"}, headers=MAQUINA).json()["job"]
    assert segundo["id"] == job_id
    assert segundo["claim_token"] != primeiro["claim_token"]
    # O token antigo não vale mais.
    resp = client.post(f"/api/ia-local/{job_id}/progresso", json={"claim_token": primeiro["claim_token"]}, headers=MAQUINA)
    assert resp.status_code == 409


def test_progresso_atualiza_etapa(app_env):
    from app.db import holder
    from app.models import IaLocalJob

    with holder.SessionLocal() as session:
        job_id = _job(session).id
    client = _client()
    job = client.get("/api/ia-local/next", params={"worker_name": "pc"}, headers=MAQUINA).json()["job"]
    resp = client.post(
        f"/api/ia-local/{job_id}/progresso",
        json={"claim_token": job["claim_token"], "etapa": "julgando o ponto 2 de 5", "palavras": 40},
        headers=MAQUINA,
    )
    assert resp.status_code == 200
    with holder.SessionLocal() as session:
        j = session.get(IaLocalJob, job_id)
        assert j.etapa == "julgando o ponto 2 de 5"
        assert j.palavras == 40


def test_correcao_passa_na_frente_da_geracao(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        _job(session, tipo="dissertativa_gerar")
        julgar_id = _job(session, tipo="dissertativa_julgar").id
    job = _client().get("/api/ia-local/next", params={"worker_name": "pc"}, headers=MAQUINA).json()["job"]
    assert job["id"] == julgar_id


def test_cancelado_devolve_409_pro_ouvinte(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        job_id = _job(session).id
    job = _client().get("/api/ia-local/next", params={"worker_name": "pc"}, headers=MAQUINA).json()["job"]
    assert _authed_client().post(f"/ia-local/jobs/{job_id}/cancelar").status_code == 200
    resp = _client().post(f"/api/ia-local/{job_id}/progresso", json={"claim_token": job["claim_token"]}, headers=MAQUINA)
    assert resp.status_code == 409


def test_progresso_mantem_a_maquina_aparecendo_ligada(app_env):
    """Durante um job longo o ouvinte não faz long-poll -- sem isto, a
    página mostraria "desligada" no meio da correção."""
    from app.db import holder
    from app.models import IaLocalPresenca

    with holder.SessionLocal() as session:
        job_id = _job(session).id
    job = _client().get("/api/ia-local/next", params={"worker_name": "pc"}, headers=MAQUINA).json()["job"]
    with holder.SessionLocal() as session:
        presenca = session.query(IaLocalPresenca).one()
        presenca.visto_em = datetime.now(timezone.utc) - timedelta(minutes=5)
        session.commit()
    assert _authed_client().get("/ia-local/status.json").json()["online"] is False
    _client().post(f"/api/ia-local/{job_id}/progresso", json={"claim_token": job["claim_token"]}, headers=MAQUINA)
    assert _authed_client().get("/ia-local/status.json").json()["online"] is True
