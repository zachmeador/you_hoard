"""First-run setup, sessions and request protection."""

import pytest


@pytest.mark.parametrize(
    "path",
    [
        "/api/videos",
        "/api/channels",
        "/api/subscriptions",
        "/api/jobs",
        "/api/settings",
        "/api/system",
    ],
)
def test_api_requires_login(anonymous, path):
    assert anonymous.client.get(path).status_code == 401


def test_setup_login_logout_and_bearer_tokens(anonymous):
    client = anonymous.client
    assert client.get("/api/auth/status").json() == {
        "authenticated": False,
        "username": None,
        "setup_required": True,
    }
    weak = client.post("/api/auth/setup", json={"username": "owner", "password": "short"})
    assert weak.status_code == 422
    created = client.post("/api/auth/setup", json={"username": "owner", "password": "long enough"})
    assert created.status_code == 200
    assert "HttpOnly" in created.headers["set-cookie"]
    assert client.get("/api/auth/status").json()["authenticated"] is True
    second = client.post("/api/auth/setup", json={"username": "other", "password": "long enough"})
    assert second.status_code == 409

    client.post("/api/auth/logout")
    assert client.get("/api/videos").status_code == 401
    wrong = client.post("/api/auth/login", json={"username": "owner", "password": "nope"})
    assert wrong.status_code == 401
    login = client.post("/api/auth/login", json={"username": "owner", "password": "long enough"})
    token = login.json()["token"]
    client.cookies.clear()
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/videos", headers=headers).status_code == 200
    client.post("/api/auth/logout", headers=headers)
    assert client.get("/api/videos", headers=headers).status_code == 401


def test_sessions_are_stored_hashed_and_expire(archive):
    token = archive.client.cookies["youhoard_session"]
    stored = archive.sql("SELECT token_hash FROM sessions")
    assert stored and all(token not in row["token_hash"] for row in stored)
    archive.sql("UPDATE sessions SET expires_at = '2000-01-01T00:00:00Z'")
    assert archive.client.get("/api/videos").status_code == 401


def test_cookie_mutations_must_be_same_origin(archive):
    archive.youtube.add("dQw4w9WgXcQ")
    cross = archive.client.post(
        "/api/videos",
        json={"url": "https://youtu.be/dQw4w9WgXcQ"},
        headers={"Origin": "https://evil.example"},
    )
    assert cross.status_code == 403
    same = archive.client.post(
        "/api/videos",
        json={"url": "https://youtu.be/dQw4w9WgXcQ"},
        headers={"Origin": "http://testserver"},
    )
    assert same.status_code == 201


def test_api_errors_are_json_not_the_spa(archive):
    for path in ("/api/nope", "/api/videos/999", "/assets/missing.js"):
        response = archive.client.get(path)
        assert response.status_code == 404
        assert response.headers["content-type"] == "application/json"
