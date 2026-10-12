import os
import pytest
from fastapi.testclient import TestClient

ADMIN_PW = "Str0ngPassw0rd!"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FQ_ADMIN_USER", "admin")
    monkeypatch.setenv("FQ_ADMIN_PASSWORD", ADMIN_PW)
    monkeypatch.setenv("FQ_JWT_SECRET", "test-secret-test-secret-test-secret-123")
    from app import config
    config.configure(data_dir=tmp_path / "data", env="development")
    from app.main import create_app
    with TestClient(create_app(start_sensor=False)) as c:
        yield c
    config.configure()


def login(client, user="admin", pw=ADMIN_PW):
    r = client.post("/api/admin/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def admin(client):
    return login(client)


def make_user(client, admin, username, role, pw="Another-Pass1234"):
    r = client.post("/api/admin/users", headers=admin, json={"username": username, "password": pw, "role": role})
    assert r.status_code == 201, r.text
    return login(client, username, pw)
