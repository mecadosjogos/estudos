from starlette.testclient import TestClient


def _build_app():
    from app.main import app

    return app


def test_home_without_session_is_rejected(app_env):
    client = TestClient(_build_app())
    response = client.get("/")
    assert response.status_code == 401


def test_token_exchange_sets_cookie_and_strips_query(app_env):
    client = TestClient(_build_app())
    response = client.get("/?k=test-token", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/"
    assert "estudos_session" in response.cookies


def test_wrong_token_does_not_authenticate(app_env):
    client = TestClient(_build_app())
    response = client.get("/?k=wrong-token", follow_redirects=False)
    assert response.status_code == 401


def test_session_cookie_grants_access(app_env):
    client = TestClient(_build_app())
    client.get("/?k=test-token")  # cookie fica no jar do client
    response = client.get("/")
    assert response.status_code == 200
    assert "TGDC" in response.text
