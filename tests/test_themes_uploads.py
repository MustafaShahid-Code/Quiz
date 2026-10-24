import base64
import io

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def test_game_config_has_active_theme(client):
    cfg = client.get("/api/game/config").json()
    assert cfg["theme"]["colors"]["bg_from"].startswith("#")
    assert cfg["slides"], "seeded sponsor slides"


def test_theme_rejects_bad_colour_and_font(client, admin):
    d = client.get("/api/admin/themes/defaults", headers=admin).json()
    d["colors"]["button_bg"] = "red; background:url(x)"
    assert client.post("/api/admin/themes", headers=admin, json={"name": "bad", "tokens": d}).status_code == 422
    d = client.get("/api/admin/themes/defaults", headers=admin).json()
    d["fonts"]["family_en"] = "Arial}</style><script>alert(1)</script>"
    assert client.post("/api/admin/themes", headers=admin, json={"name": "bad2", "tokens": d}).status_code == 422


def test_theme_create_activate_export_import(client, admin):
    d = client.get("/api/admin/themes/defaults", headers=admin).json()
    d["colors"]["button_bg"] = "#12a150"
    t = client.post("/api/admin/themes", headers=admin, json={"name": "Client A", "tokens": d})
    assert t.status_code == 201
    tid = t.json()["id"]
    assert client.post(f"/api/admin/themes/{tid}/activate", headers=admin).status_code == 200
    assert client.get("/api/game/config").json()["theme"]["colors"]["button_bg"] == "#12a150"
    exp = client.get(f"/api/admin/themes/{tid}/export", headers=admin).json()
    assert client.post("/api/admin/themes/import", headers=admin, json=exp).status_code == 201
    assert client.delete(f"/api/admin/themes/{tid}", headers=admin).status_code == 409  # active theme


def test_upload_accepts_png_rejects_script_and_fake(client, admin):
    ok = client.post("/api/admin/assets", headers=admin, files={"file": ("a.png", PNG, "image/png")})
    assert ok.status_code == 201
    url = ok.json()["url"]
    got = client.get(url)
    assert got.status_code == 200 and got.headers["content-type"].startswith("image/png")
    assert "sandbox" in got.headers.get("content-security-policy", "")
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
    assert client.post("/api/admin/assets", headers=admin, files={"file": ("x.svg", svg, "image/svg+xml")}).status_code == 422
    assert client.post("/api/admin/assets", headers=admin, files={"file": ("x.png", b"<html>not an image</html>", "image/png")}).status_code == 422
    assert client.post("/api/admin/assets", headers=admin, files={"file": ("x.exe", b"MZ\x90\x00", "application/octet-stream")}).status_code == 422


def test_media_path_traversal(client):
    assert client.get("/media/../quiz.db").status_code in (404, 422)
    assert client.get("/media/..%2f..%2fquiz.db").status_code in (404, 422)


def test_security_headers(client):
    r = client.get("/game/")
    assert "content-security-policy" in r.headers and r.headers.get("x-content-type-options") == "nosniff"


def test_slide_crud_and_schedule(client, admin):
    r = client.post("/api/admin/slides", headers=admin, json={"title_en": "Promo", "body_en": "hello", "duration_ms": 4000, "enabled": True})
    assert r.status_code == 201
    sid = r.json()["id"]
    future = client.put(f"/api/admin/slides/{sid}", headers=admin, json={"title_en": "Promo", "duration_ms": 4000, "enabled": True, "starts_at": "2999-01-01T00:00:00"})
    assert future.status_code == 200
    titles = [s["title_en"] for s in client.get("/api/game/config").json()["slides"]]
    assert "Promo" not in titles
    assert client.delete(f"/api/admin/slides/{sid}", headers=admin).status_code == 200


def test_confirm_settings_validated(client, admin):
    assert client.put("/api/admin/settings", headers=admin, json={"values": {"confirm_delay_ms": 100}}).status_code == 422
    assert client.put("/api/admin/settings", headers=admin, json={"values": {"confirm_delay_ms": 2500}}).status_code == 200
    assert client.get("/api/game/config").json()["settings"]["confirm_delay_ms"] == 2500


def test_login_branding_is_public_and_admin_controlled(client, admin):
    r = client.get("/api/admin/branding").json()
    assert r["login"]["layout"] == "split" and r["login"]["features"]
    assert client.put("/api/admin/settings", json={"values": {"login_layout": "centered", "login_headline": "Hi", "login_color_2": "#112233"}}, headers=admin).status_code == 200
    r = client.get("/api/admin/branding").json()["login"]
    assert r["layout"] == "centered" and r["headline"] == "Hi" and r["color_2"] == "#112233"
    assert client.put("/api/admin/settings", json={"values": {"login_layout": "weird"}}, headers=admin).status_code == 422
    assert client.put("/api/admin/settings", json={"values": {"login_color_2": "red"}}, headers=admin).status_code == 422


def test_default_favicon_assets_are_served(client):
    for path in ("/static/brand/favicon.svg", "/static/brand/favicon.ico", "/static/brand/apple-touch-icon.png"):
        assert client.get(path).status_code == 200, path
    assert client.get("/favicon.ico", follow_redirects=False).status_code in (302, 307)
    assert "/static/brand/favicon.svg" in client.get("/game/").text and "/static/brand/favicon.svg" in client.get("/admin/").text
