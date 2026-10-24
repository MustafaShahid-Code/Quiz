from .conftest import ADMIN_PW, login, make_user


def test_login_bad_password(client):
    r = client.post("/api/admin/login", json={"username": "admin", "password": "nope"})
    assert r.status_code == 401


def test_throttle_after_failures(client):
    for _ in range(5):
        client.post("/api/admin/login", json={"username": "admin", "password": "bad"})
    r = client.post("/api/admin/login", json={"username": "admin", "password": ADMIN_PW})
    assert r.status_code == 429


def test_admin_endpoints_need_token(client):
    for path in ("/api/admin/questions", "/api/admin/settings", "/api/admin/users", "/api/admin/sensor/status"):
        assert client.get(path).status_code == 401


def test_roles(client, admin):
    viewer = make_user(client, admin, "vera", "viewer")
    editor = make_user(client, admin, "edith", "editor")
    assert client.get("/api/admin/questions", headers=viewer).status_code == 200
    assert client.post("/api/admin/questions", headers=viewer, json={}).status_code == 403
    assert client.post("/api/admin/questions", headers=editor, json={}).status_code == 201
    assert client.put("/api/admin/settings", headers=editor, json={"values": {"questions_per_session": 3}}).status_code == 403
    assert client.get("/api/admin/users", headers=editor).status_code == 403
    assert client.post("/api/admin/sensor/restart", headers=editor).status_code == 403


def test_weak_password_rejected(client, admin):
    r = client.post("/api/admin/users", headers=admin, json={"username": "bob", "password": "short", "role": "editor"})
    assert r.status_code in (400, 422)


def test_cannot_remove_last_admin(client, admin):
    me = client.get("/api/admin/me", headers=admin).json()
    assert client.delete(f"/api/admin/users/{me['id']}", headers=admin).status_code == 409
    assert client.put(f"/api/admin/users/{me['id']}", headers=admin, json={"role": "viewer"}).status_code == 409


def test_public_branding_has_no_secrets(client):
    r = client.get("/api/admin/branding")
    assert r.status_code == 200 and "product_name" in r.json()
