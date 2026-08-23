from datetime import datetime, timedelta, timezone

from starlette.testclient import TestClient


def _build_app():
    from app.main import app

    return app


def test_home_without_session_redirects_to_login(app_env):
    client = TestClient(_build_app())
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_success_sets_cookie_and_grants_access(app_env):
    client = TestClient(_build_app())
    response = client.post("/login", data={"username": "admin", "senha": "admin"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "estudos_session" in response.cookies

    home = client.get("/")
    assert home.status_code == 200
    assert "TGDC" in home.text


def test_login_wrong_password_rejected(app_env):
    client = TestClient(_build_app())
    response = client.post("/login", data={"username": "admin", "senha": "errada"}, follow_redirects=False)
    assert response.status_code == 303
    assert "erro=" in response.headers["location"]
    assert "estudos_session" not in response.cookies


def _create_user(session, **overrides):
    from app.models import User
    from app.security import hash_password

    defaults = {"username": "membro", "senha_hash": hash_password("senha123"), "papel": "usuario", "status": "pendente"}
    defaults.update(overrides)
    user = User(**defaults)
    session.add(user)
    session.commit()
    return user


def test_pending_user_cannot_log_in(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        _create_user(session, status="pendente")

    client = TestClient(_build_app())
    response = client.post("/login", data={"username": "membro", "senha": "senha123"}, follow_redirects=True)
    assert "aprovação" in response.text
    assert "estudos_session" not in client.cookies


def test_revoked_user_cannot_log_in(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        _create_user(session, status="revogado")

    client = TestClient(_build_app())
    response = client.post("/login", data={"username": "membro", "senha": "senha123"}, follow_redirects=True)
    assert "não autorizado" in response.text.lower()
    assert "estudos_session" not in client.cookies


def test_expired_temporary_access_rejected(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        _create_user(session, status="aprovado", expira_em=datetime.now(timezone.utc) - timedelta(days=1))

    client = TestClient(_build_app())
    response = client.post("/login", data={"username": "membro", "senha": "senha123"}, follow_redirects=True)
    assert "expirado" in response.text.lower()
    assert "estudos_session" not in client.cookies


def test_approved_regular_user_gets_403_on_admin_route(app_env):
    from app.db import holder

    with holder.SessionLocal() as session:
        _create_user(session, status="aprovado", papel="usuario")

    client = TestClient(_build_app())
    client.post("/login", data={"username": "membro", "senha": "senha123"})
    response = client.get("/admin/seguranca")
    assert response.status_code == 403


def test_register_creates_pending_user_who_cannot_log_in_yet(app_env):
    client = TestClient(_build_app())
    response = client.post(
        "/registrar",
        data={"username": "novo", "senha": "senha123", "confirmar_senha": "senha123"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/login?cadastro=1"

    login_response = client.post("/login", data={"username": "novo", "senha": "senha123"}, follow_redirects=True)
    assert "aprovação" in login_response.text
