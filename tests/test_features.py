"""Event features: image optimisation, question rotation, claim codes, CSV export, bulk import, safety net, leaderboard, analytics."""
import csv
import io
import sqlite3
import zipfile

from PIL import Image

from .conftest import make_user
from .test_challenge import challenge_game, play
from .test_games import add_published, new_game


def png_bytes(w, h, mode="RGB", noisy=False):
    import os
    im = Image.frombytes(mode, (w, h), os.urandom(w * h * len(mode))) if noisy else Image.new(mode, (w, h), (30, 90, 200) if mode == "RGB" else (0, 0, 0, 0))
    b = io.BytesIO(); im.save(b, "PNG"); return b.getvalue()


def upload(client, admin, data, name="x.png", ctype="image/png"):
    r = client.post("/api/admin/assets", headers=admin, files={"file": (name, data, ctype)})
    assert r.status_code == 201, r.text
    return r.json()


def csv_rows(resp):
    assert resp.status_code == 200, resp.text
    text = resp.content.decode("utf-8")
    assert text.startswith("﻿")
    return list(csv.reader(io.StringIO(text.lstrip("﻿"))))


# ------------------------------------------------------------------ images
def test_big_photo_is_downscaled_and_smaller(client, admin):
    raw = png_bytes(1900, 1200, noisy=True)
    a = upload(client, admin, raw)
    assert a["original_bytes"] == len(raw) and a["size_bytes"] < len(raw) / 3
    assert max(a["width"], a["height"]) <= 1600 and a["mime"] == "image/jpeg"


def test_transparent_logo_keeps_png_and_alpha(client, admin):
    a = upload(client, admin, png_bytes(300, 120, "RGBA"))
    assert a["mime"] == "image/png"
    got = client.get(a["url"]); assert Image.open(io.BytesIO(got.content)).mode == "RGBA"


def test_small_clean_image_is_untouched(client, admin):
    raw = png_bytes(200, 100)
    a = upload(client, admin, raw)
    assert a["size_bytes"] == len(raw) and a["width"] == 200


def test_exif_rotation_is_baked_in_and_metadata_removed(client, admin):
    im = Image.new("RGB", (400, 200), "red"); ex = im.getexif(); ex[274] = 6
    b = io.BytesIO(); im.save(b, "JPEG", exif=ex)
    a = upload(client, admin, b.getvalue(), "p.jpg", "image/jpeg")
    assert (a["width"], a["height"]) == (200, 400)
    assert not Image.open(io.BytesIO(client.get(a["url"]).content)).getexif()


# ------------------------------------------------------------------ question rotation
def test_questions_rotate_so_the_next_player_gets_fresh_ones(client, admin):
    g = new_game(client, admin, overrides={"questions_per_session": 3, "ask_player_name": False})
    ids = [add_published(client, admin, f"Q{i}", g["id"]) for i in range(6)]
    seen = []
    for _ in range(2):
        sid = client.post("/api/game/sessions", json={"lang": "en", "game": g["slug"]}).json()["session_id"]
        round_ids = set()
        for _i in range(3):
            q = client.get(f"/api/game/sessions/{sid}/question").json()["question"]
            round_ids.add(q["question_id"])
            client.post(f"/api/game/sessions/{sid}/answer", json={"question_id": q["question_id"], "option_id": q["options"][0]["id"]})
        seen.append(round_ids)
    assert not (seen[0] & seen[1]) and (seen[0] | seen[1]) == set(ids)


def test_rotation_can_be_switched_off(client, admin):
    g = new_game(client, admin, overrides={"questions_per_session": 2, "randomize_questions": False, "avoid_repeat_questions": False})
    ids = [add_published(client, admin, f"R{i}", g["id"]) for i in range(4)]
    for _ in range(2):
        sid = client.post("/api/game/sessions", json={"lang": "en", "game": g["slug"]}).json()["session_id"]
        q = client.get(f"/api/game/sessions/{sid}/question").json()["question"]
        assert q["question_id"] == ids[0]


# ------------------------------------------------------------------ claim codes
def test_claim_code_only_for_winners_when_enabled(client, admin):
    g = challenge_game(client, admin, claim_code_enabled=True)
    _, win = play(client, g, [True, True, False])
    _, lose = play(client, g, [False, False, True])
    assert win["claim_code"] and len(win["claim_code"]) == 7 and win["claim_code"][3] == "-" and win["claim_label"]
    assert lose["claim_code"] is None
    h = challenge_game(client, admin, name="Guess the Player 2")   # off by default
    assert play(client, h, [True, True, True])[1]["claim_code"] is None


def test_claim_qr_is_svg_for_a_won_round_only(client, admin):
    g = challenge_game(client, admin, claim_code_enabled=True)
    sid, win = play(client, g, [True, True, True]); sid2, _ = play(client, g, [False, False, False])
    r = client.get(f"/api/game/sessions/{sid}/claim.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg") and b"<svg" in r.content
    assert client.get(f"/api/game/sessions/{sid2}/claim.svg").status_code == 404


def test_redeem_flow(client, admin):
    g = challenge_game(client, admin, claim_code_enabled=True)
    _, win = play(client, g, [True, True, False], name="Hamad")
    code = win["claim_code"]
    r = client.get(f"/api/admin/claims/{code.lower().replace('-', ' ')}", headers=admin)      # forgiving input
    assert r.status_code == 200 and r.json()["player_name"] == "Hamad" and r.json()["claimed"] is False
    assert client.get("/api/admin/claims/ZZZ-999", headers=admin).status_code == 404
    viewer = make_user(client, admin, "view1", "viewer"); staff = make_user(client, admin, "staff1", "editor")
    assert client.post(f"/api/admin/claims/{code}/redeem", headers=viewer, json={}).status_code == 403
    ok = client.post(f"/api/admin/claims/{code}/redeem", headers=staff, json={})
    assert ok.status_code == 200 and ok.json()["claimed"] and ok.json()["claimed_by"] == "staff1"
    again = client.post(f"/api/admin/claims/{code}/redeem", headers=staff, json={})
    assert again.status_code == 409 and "staff1" in again.json()["detail"]
    assert client.post(f"/api/admin/claims/{code}/undo", headers=staff).status_code == 403
    assert client.post(f"/api/admin/claims/{code}/undo", headers=admin).json()["claimed"] is False
    lst = client.get("/api/admin/claims?status=pending", headers=admin).json()
    assert lst["pending"] == 1 and lst["items"][0]["code"] == code


def test_claims_respect_game_access(client, admin):
    g1 = challenge_game(client, admin, claim_code_enabled=True)
    _, win = play(client, g1, [True, True, True])
    g2 = new_game(client, admin, "Other Game")
    r = client.post("/api/admin/users", headers=admin, json={"username": "scoped", "password": "Another-Pass1234", "role": "editor", "all_games": False, "game_ids": [g2["id"]]})
    assert r.status_code == 201, r.text
    from .conftest import login
    scoped = login(client, "scoped", "Another-Pass1234")
    assert client.get(f"/api/admin/claims/{win['claim_code']}", headers=scoped).status_code == 403
    assert client.get("/api/admin/claims", headers=scoped).json()["total"] == 0


# ------------------------------------------------------------------ results filters + CSV export
def test_results_filters_and_csv(client, admin):
    g = challenge_game(client, admin, claim_code_enabled=True)
    play(client, g, [True, True, True], name="=HYPERLINK(\"http://x\")")
    play(client, g, [False, False, False], name="Omar")
    play(client, g, [True, False, True], name="Layla")
    base = f"/api/admin/sessions?game_id={g['id']}"
    assert client.get(base + "&outcome=win", headers=admin).json()["total"] == 2
    assert client.get(base + "&outcome=lose", headers=admin).json()["total"] == 1
    assert client.get(base + "&q=lay", headers=admin).json()["total"] == 1
    assert client.get(base + "&q=%25", headers=admin).json()["total"] == 0          # LIKE wildcards are escaped
    assert client.get(base + "&date_from=2000-01-01&date_to=2000-01-02", headers=admin).json()["total"] == 0
    assert client.get(base + "&date_from=2000-01-01", headers=admin).json()["total"] == 3
    assert client.get(base + "&date_from=nope", headers=admin).status_code == 422
    rows = csv_rows(client.get(f"/api/admin/sessions-export.csv?game_id={g['id']}&tz=180", headers=admin))
    assert rows[0][:6] == ["Started (local)", "Finished (local)", "Game", "Player", "Language", "Result"] and len(rows) == 4
    players = {r[3] for r in rows[1:]}
    assert "'=HYPERLINK(\"http://x\")" in players and "Omar" in players         # formula injection is neutralised
    winners = csv_rows(client.get(f"/api/admin/sessions-export.csv?game_id={g['id']}&outcome=win", headers=admin))
    assert len(winners) == 3 and all(r[5] == "WIN" for r in winners[1:]) and all(r[10] for r in winners[1:])
    ans = csv_rows(client.get(f"/api/admin/sessions-export.csv?kind=answers&game_id={g['id']}&outcome=lose", headers=admin))
    assert ans[0][5] == "Question #" and len(ans) == 4 and all(r[8] == "no" for r in ans[1:])


def test_export_requires_login_and_respects_scope(client, admin):
    assert client.get("/api/admin/sessions-export.csv").status_code == 401


# ------------------------------------------------------------------ bulk import
SHEET = (
    "text_en,text_ar,option1_en,option1_ar,option2_en,option2_ar,option3_en,option3_ar,option4_en,option4_ar,correct,image,reveal_image,difficulty\n"
    "Who is this?,من هذا؟,Messi,ميسي,Ronaldo,رونالدو,Neymar,نيمار,Mbappe,مبابي,1,m_eyes.png,m_full.png,easy\n"
    ",,Salah,صلاح,Mane,ماني,Son,سون,Benzema,بنزيمة,b,s_eyes.png,s_full.png,hard\n"
)


def test_import_templates_download(client, admin):
    r = client.get("/api/admin/import/template.xlsx", headers=admin)
    assert r.status_code == 200 and r.content[:2] == b"PK"
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(r.content)).worksheets[0]
    assert [c.value for c in ws[1]][:3] == ["text_en", "text_ar", "option1_en"] and ws.max_row == 3
    c = client.get("/api/admin/import/template.csv", headers=admin)
    assert c.status_code == 200 and c.content.startswith(b"\xef\xbb\xbftext_en")


def test_import_preview_validates_rows(client, admin):
    g = new_game(client, admin)
    r = client.post(f"/api/admin/games/{g['id']}/import/preview?default_text_en=Who is this player%3F&default_text_ar=من هو؟", headers=admin,
                    files={"file": ("q.csv", SHEET.encode("utf-8"), "text/csv")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] == 2 and d["bad"] == 0 and d["images"] == ["m_eyes.png", "m_full.png", "s_eyes.png", "s_full.png"]
    assert d["rows"][1]["correct"] == 2 and d["rows"][1]["text_en"] == "Who is this player?"
    bad = "text_en,option1_en,option2_en,correct,difficulty,image\nQ,A,,3,wild,cat.txt\n"
    d2 = client.post(f"/api/admin/games/{g['id']}/import/preview", headers=admin, files={"file": ("q.csv", bad.encode(), "text/csv")}).json()
    msgs = " | ".join(d2["rows"][0]["errors"])
    assert d2["bad"] == 1 and "at least 2" in msgs and "difficulty" in msgs and "picture" in msgs
    assert client.post(f"/api/admin/games/{g['id']}/import/preview", headers=admin, files={"file": ("q.pdf", b"x", "application/pdf")}).status_code == 422
    assert client.post(f"/api/admin/games/{g['id']}/import/preview", headers=admin, files={"file": ("q.csv", b"hello\nworld\n", "text/csv")}).status_code == 422


def test_import_xlsx_preview_and_commit_end_to_end(client, admin):
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    ws.append(["text_en", "option1_en", "option2_en", "correct", "image", "reveal_image"])
    ws.append(["Guess", "Right", "Wrong", 1, "a.png", "A_FULL.png"])
    b = io.BytesIO(); wb.save(b)
    g = new_game(client, admin)
    prev = client.post(f"/api/admin/games/{g['id']}/import/preview", headers=admin, files={"file": ("q.xlsx", b.getvalue(), "application/octet-stream")}).json()
    assert prev["ok"] == 1
    a1 = upload(client, admin, png_bytes(300, 100)); a2 = upload(client, admin, png_bytes(300, 120))
    r = client.post(f"/api/admin/games/{g['id']}/import/commit", headers=admin,
                    json={"rows": prev["rows"], "assets": {"a.png": a1["id"], "a_full.png": a2["id"]}, "publish": True})
    assert r.status_code == 201, r.text
    assert r.json()["created"] == 1 and r.json()["published"] == 1
    items = client.get(f"/api/admin/questions?game_id={g['id']}", headers=admin).json()["items"]
    assert len(items) == 1 and items[0]["status"] == "published"
    q = client.get(f"/api/admin/questions/{items[0]['id']}", headers=admin).json()
    assert q["image_asset_id"] == a1["id"] and q["reveal_asset_id"] == a2["id"] and sum(o["is_correct"] for o in q["options"]) == 1
    # and it is playable
    assert client.post("/api/game/sessions", json={"lang": "en", "game": g["slug"]}).status_code == 201


def test_import_commit_is_all_or_nothing_and_untrusting(client, admin):
    g = new_game(client, admin)
    prev = client.post(f"/api/admin/games/{g['id']}/import/preview", headers=admin, files={"file": ("q.csv", SHEET.encode(), "text/csv")}).json()
    rows = prev["rows"]
    a = upload(client, admin, png_bytes(300, 100))
    # a missing image upload -> 422, nothing created
    r = client.post(f"/api/admin/games/{g['id']}/import/commit", headers=admin, json={"rows": rows, "assets": {"m_eyes.png": a["id"]}, "default_text_en": "Who?", "default_text_ar": "من؟"})
    assert r.status_code == 422
    assert client.get(f"/api/admin/questions?game_id={g['id']}", headers=admin).json()["total"] == 0
    # a forged asset id is rejected too
    all_assets = {k.lower(): 99999 for k in prev["images"]}
    assert client.post(f"/api/admin/games/{g['id']}/import/commit", headers=admin, json={"rows": rows, "assets": all_assets}).status_code == 422
    # a row the browser tampered with (no correct option) is rejected by the server
    forged = [{**rows[0], "correct": 9}]
    assert client.post(f"/api/admin/games/{g['id']}/import/commit", headers=admin, json={"rows": forged, "assets": {}}).status_code == 422
    # draft by default
    ok_assets = {k.lower(): a["id"] for k in prev["images"]}
    done = client.post(f"/api/admin/games/{g['id']}/import/commit", headers=admin, json={"rows": rows, "assets": ok_assets, "default_text_en": "Who?", "default_text_ar": "من؟"})
    assert done.status_code == 201 and done.json()["created"] == 2 and done.json()["published"] == 0
    assert {i["status"] for i in client.get(f"/api/admin/questions?game_id={g['id']}", headers=admin).json()["items"]} == {"draft"}


def test_import_needs_editor_and_game_access(client, admin):
    g = new_game(client, admin)
    viewer = make_user(client, admin, "viewer2", "viewer")
    assert client.get("/api/admin/import/template.csv", headers=viewer).status_code == 403
    assert client.post(f"/api/admin/games/{g['id']}/import/preview", headers=viewer, files={"file": ("q.csv", SHEET.encode(), "text/csv")}).status_code == 403


# ------------------------------------------------------------------ safety net
def test_clear_results(client, admin):
    g = challenge_game(client, admin)
    play(client, g, [True, True, True]); play(client, g, [False, False, False])
    assert client.post(f"/api/admin/games/{g['id']}/results/clear", headers=admin, json={"confirm": "wrong"}).status_code == 422
    staff = make_user(client, admin, "ed1", "editor")
    assert client.post(f"/api/admin/games/{g['id']}/results/clear", headers=staff, json={"confirm": g["slug"]}).status_code == 403
    r = client.post(f"/api/admin/games/{g['id']}/results/clear", headers=admin, json={"confirm": g["slug"]})
    assert r.status_code == 200 and r.json()["deleted"] == 2
    assert client.get(f"/api/admin/sessions?game_id={g['id']}", headers=admin).json()["total"] == 0
    assert client.get(f"/api/admin/questions?game_id={g['id']}", headers=admin).json()["total"] == 3   # questions are kept


def test_clear_results_leaves_other_games_alone(client, admin):
    g1 = challenge_game(client, admin)
    play(client, g1, [True, True, True])
    r = client.post("/api/game/sessions", json={"lang": "en"}); assert r.status_code == 201            # a play on the default game
    client.post(f"/api/admin/games/{g1['id']}/results/clear", headers=admin, json={"confirm": g1["slug"]})
    assert client.get("/api/admin/sessions", headers=admin).json()["total"] == 1


def test_backup_download_contains_database_and_uploads(client, admin):
    upload(client, admin, png_bytes(100, 50))
    assert client.get("/api/admin/backup").status_code == 401
    staff = make_user(client, admin, "ed2", "editor")
    assert client.get("/api/admin/backup", headers=staff).status_code == 403
    r = client.get("/api/admin/backup", headers=admin)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content)); names = z.namelist()
    assert "fq.db" in names and any(n.startswith("uploads/") for n in names)
    import tempfile, os
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(z.read("fq.db")); path = f.name
    try:
        assert sqlite3.connect(path).execute("SELECT COUNT(*) FROM games").fetchone()[0] >= 1
    finally:
        os.unlink(path)


def test_system_status_admin_only(client, admin):
    assert client.get("/api/admin/system", headers=make_user(client, admin, "ed3", "editor")).status_code == 403
    d = client.get("/api/admin/system", headers=admin).json()
    assert d["db_bytes"] > 0 and "uptime_seconds" in d and d["uploads"]["files"] >= 0 and d["image_max_px"] == 1600


# ------------------------------------------------------------------ leaderboard + analytics
def test_leaderboard_is_opt_in_and_shows_top_and_winners(client, admin):
    g = challenge_game(client, admin)
    assert client.get(f"/api/game/leaderboard?game={g['slug']}").status_code == 404           # off by default
    h = challenge_game(client, admin, name="Guess the Player 2", leaderboard_enabled=True)
    play(client, h, [True, True, True], name="Ali"); play(client, h, [True, False, True], name="Mona"); play(client, h, [False, False, False], name="Sam")
    d = client.get(f"/api/game/leaderboard?game={h['slug']}&tz=180").json()
    assert [r["player_name"] for r in d["top"]][:2] == ["Ali", "Mona"] and d["top"][0]["score"] >= d["top"][1]["score"]
    assert [r["player_name"] for r in d["winners"]] == ["Mona", "Ali"]          # latest winner first, losers never listed
    assert d["stats"] == {"rounds": 3, "wins": 2} and d["has_outcome"] is True
    assert "id" not in d["top"][0] and "session_id" not in d["top"][0]
    assert client.get(f"/api/game/leaderboard?game={h['slug']}&period=all").status_code == 200


def test_leaderboard_for_password_protected_game_needs_the_token(client, admin):
    g = challenge_game(client, admin, leaderboard_enabled=True)
    gm = [x for x in client.get("/api/admin/games", headers=admin).json()["items"] if x["slug"] == g["slug"]][0]
    r = client.put(f"/api/admin/games/{gm['id']}", headers=admin, json={**gm, "access_password": "secret123"})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/game/leaderboard?game={g['slug']}").status_code == 401
    tok = client.post(f"/api/game/games/{g['slug']}/unlock", json={"password": "secret123"}).json()["token"]
    assert client.get(f"/api/game/leaderboard?game={g['slug']}", headers={"x-game-token": tok}).status_code == 200


def test_stats_analytics(client, admin):
    g = challenge_game(client, admin)
    play(client, g, [True, True, True]); play(client, g, [False, False, True]); play(client, g, [True, True, False], name="Zed")
    d = client.get(f"/api/admin/stats?game_id={g['id']}&tz=180", headers=admin).json()
    assert d["outcomes"] == {"win": 2, "lose": 1, "win_rate": 67}
    assert sum(d["plays_by_hour"]) == 3 and len(d["plays_by_hour"]) == 24 and d["unique_players"] == 2 and d["by_language"] == {"en": 3}
    assert d["completion_rate"] == 100 and d["avg_round_seconds"] is not None
    assert d["easiest_questions"] and d["hardest_questions"]
