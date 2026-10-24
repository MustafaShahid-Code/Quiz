"""Multi-game: every game owns its questions and nothing leaks between games."""
from .conftest import make_user


def q_payload(text, game_id=None, correct=0):
    return {"text_en": text, "text_ar": text + " ع", "game_id": game_id,
            "options": [{"label_en": f"{text}-{i}", "label_ar": f"{text}-{i} ع", "is_correct": i == correct} for i in range(4)]}


def new_game(client, admin, name="Guess the Player", **kw):
    r = client.post("/api/admin/games", headers=admin, json={"name_en": name, "name_ar": "خمن اللاعب", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def add_published(client, admin, text, game_id):
    r = client.post("/api/admin/questions", headers=admin, json=q_payload(text, game_id))
    assert r.status_code == 201, r.text
    qid = r.json()["id"]
    r = client.post(f"/api/admin/questions/{qid}/status", headers=admin, json={"status": "published"})
    assert r.status_code == 200, r.text
    return qid


def test_default_game_owns_seeded_questions(client, admin):
    games = client.get("/api/admin/games", headers=admin).json()["items"]
    assert len(games) == 1 and games[0]["is_default"] and games[0]["slug"] == "football"
    assert games[0]["question_count"] > 0


def test_game_crud_and_slug(client, admin):
    g = new_game(client, admin)
    assert g["slug"] == "guess-the-player" and not g["is_default"]
    assert client.post("/api/admin/games", headers=admin, json={"name_en": "Guess the Player"}).status_code == 409
    assert client.post("/api/admin/games", headers=admin, json={"name_en": "x", "slug": "Bad Slug"}).status_code == 422
    assert client.post("/api/admin/games", headers=admin, json={"name_en": "x", "overrides": {"idle_reset_seconds": 5}}).status_code == 422
    r = client.put(f"/api/admin/games/{g['id']}", headers=admin, json={**g, "overrides": {"questions_per_session": 3}})
    assert r.status_code == 200 and r.json()["overrides"] == {"questions_per_session": 3}


def test_questions_never_mix_between_games(client, admin):
    g = new_game(client, admin)
    mine = {add_published(client, admin, f"Who is player {i}", g["id"]) for i in range(3)}
    # a session in the new game only ever contains its own questions
    for _ in range(5):
        sid = client.post("/api/game/sessions", json={"lang": "en", "game": g["slug"]}).json()["session_id"]
        seen = set()
        while True:
            cur = client.get(f"/api/game/sessions/{sid}/question").json()
            if cur["finished"]:
                break
            qid = cur["question"]["question_id"]
            seen.add(qid)
            client.post(f"/api/game/sessions/{sid}/timeout", json={"question_id": qid})
        assert seen and seen <= mine
    # and the default game never serves them
    default_q = {q["id"] for q in client.get("/api/admin/questions?game_id=%d&page_size=100" % 1, headers=admin).json()["items"]}
    assert not (default_q & mine)
    for _ in range(5):
        sid = client.post("/api/game/sessions", json={"lang": "en"}).json()["session_id"]
        cur = client.get(f"/api/game/sessions/{sid}/question").json()
        assert cur["question"]["question_id"] not in mine


def test_empty_game_cannot_start_and_is_hidden(client, admin):
    g = new_game(client, admin)
    r = client.post("/api/game/sessions", json={"lang": "en", "game": g["slug"]})
    assert r.status_code == 409
    slugs = [x["slug"] for x in client.get("/api/game/games").json()["items"]]
    assert g["slug"] not in slugs and "football" in slugs
    add_published(client, admin, "Eyes one", g["id"])
    slugs = [x["slug"] for x in client.get("/api/game/games").json()["items"]]
    assert g["slug"] in slugs


def test_disabled_and_unknown_games_rejected(client, admin):
    g = new_game(client, admin)
    add_published(client, admin, "Eyes one", g["id"])
    client.put(f"/api/admin/games/{g['id']}", headers=admin, json={**g, "enabled": False})
    assert client.post("/api/game/sessions", json={"lang": "en", "game": g["slug"]}).status_code == 404
    assert client.get("/api/game/config?game=nope").status_code == 404


def test_per_game_settings_override_and_global_fallback(client, admin):
    g = new_game(client, admin, overrides={"questions_per_session": 2, "title_en": "Guess Who?", "answer_time_limit_ms": 9000})
    for i in range(4):
        add_published(client, admin, f"Eyes {i}", g["id"])
    cfg = client.get(f"/api/game/config?game={g['slug']}").json()
    assert cfg["settings"]["title_en"] == "Guess Who?" and cfg["settings"]["answer_time_limit_ms"] == 9000
    assert client.post("/api/game/sessions", json={"lang": "en", "game": g["slug"]}).json()["total"] == 2
    base = client.get("/api/game/config").json()
    assert base["settings"]["title_en"] != "Guess Who?" and base["game"]["slug"] == "football"


def test_delete_rules(client, admin):
    g = new_game(client, admin)
    qid = add_published(client, admin, "Eyes one", g["id"])
    assert client.delete(f"/api/admin/games/{g['id']}", headers=admin).status_code == 409   # has questions
    assert client.delete("/api/admin/games/1", headers=admin).status_code == 409            # default
    client.delete(f"/api/admin/questions/{qid}", headers=admin)
    assert client.delete(f"/api/admin/games/{g['id']}", headers=admin).status_code == 200


def test_moving_question_between_games_and_sessions_filter(client, admin):
    g = new_game(client, admin)
    qid = add_published(client, admin, "Eyes one", g["id"])
    q = client.get(f"/api/admin/questions/{qid}", headers=admin).json()
    assert q["game_id"] == g["id"] and q["game_name_en"] == "Guess the Player"
    sid = client.post("/api/game/sessions", json={"lang": "en", "game": g["slug"]}).json()["session_id"]
    rows = client.get(f"/api/admin/sessions?game_id={g['id']}", headers=admin).json()
    assert rows["total"] == 1 and rows["items"][0]["id"] == sid and rows["items"][0]["game_name"] == "Guess the Player"
    assert client.get("/api/admin/sessions?game_id=1", headers=admin).json()["total"] == 0
    assert client.get(f"/api/admin/stats?game_id={g['id']}", headers=admin).json()["questions"]["published"] == 1


def test_only_admin_manages_games(client, admin):
    viewer = make_user(client, admin, "vee", "viewer")
    assert client.get("/api/admin/games", headers=viewer).status_code == 200
    assert client.post("/api/admin/games", headers=viewer, json={"name_en": "x"}).status_code == 403


# ------------------------------------------------------------------ per-game staff & branding
def scoped_user(client, admin, name, role, game_ids):
    r = client.post("/api/admin/users", headers=admin, json={"username": name, "password": "Another-Pass1234", "role": role,
                                                             "all_games": False, "game_ids": game_ids})
    assert r.status_code == 201, r.text
    from .conftest import login
    return login(client, name, "Another-Pass1234")


def test_scoped_staff_only_see_and_edit_their_game(client, admin):
    g = new_game(client, admin)
    mine = add_published(client, admin, "Eyes one", g["id"])
    football_q = client.get("/api/admin/questions?game_id=1&page_size=1", headers=admin).json()["items"][0]["id"]
    ana = scoped_user(client, admin, "ana", "editor", [g["id"]])
    games = client.get("/api/admin/games", headers=ana).json()["items"]
    assert [x["id"] for x in games] == [g["id"]]
    qs = client.get("/api/admin/questions?page_size=100", headers=ana).json()
    assert {q["id"] for q in qs["items"]} == {mine}
    assert client.get(f"/api/admin/questions/{football_q}", headers=ana).status_code == 403
    assert client.put(f"/api/admin/questions/{football_q}", headers=ana, json=q_payload("hack", g["id"])).status_code == 403
    assert client.delete(f"/api/admin/questions/{football_q}", headers=ana).status_code == 403
    # cannot create into another game, but may omit game_id (single-game account) and gets her own
    assert client.post("/api/admin/questions", headers=ana, json=q_payload("x", 1)).status_code == 403
    r = client.post("/api/admin/questions", headers=ana, json=q_payload("auto game"))
    assert r.status_code == 201 and r.json()["game_id"] == g["id"]
    # cannot create/manage games or users
    assert client.post("/api/admin/games", headers=ana, json={"name_en": "z"}).status_code == 403
    assert client.get("/api/admin/users", headers=ana).status_code == 403
    assert client.get("/api/admin/games/1", headers=ana).status_code == 403


def test_scoped_results_and_stats_are_isolated(client, admin):
    g = new_game(client, admin)
    add_published(client, admin, "Eyes one", g["id"])
    client.post("/api/game/sessions", json={"lang": "en", "game": g["slug"]})
    client.post("/api/game/sessions", json={"lang": "en"})
    other = client.post("/api/game/sessions", json={"lang": "en"}).json()["session_id"]
    viewer = scoped_user(client, admin, "vic", "viewer", [g["id"]])
    assert client.get("/api/admin/sessions", headers=viewer).json()["total"] == 1
    assert client.get("/api/admin/sessions?game_id=1", headers=viewer).status_code == 403
    assert client.get(f"/api/admin/sessions/{other}", headers=viewer).status_code == 403
    assert client.get("/api/admin/stats", headers=viewer).json()["sessions"]["total"] == 1
    assert client.get("/api/admin/stats", headers=admin).json()["sessions"]["total"] == 3


def test_scoped_account_validation_and_admin_override(client, admin):
    r = client.post("/api/admin/users", headers=admin, json={"username": "bob", "password": "Another-Pass1234", "role": "editor", "all_games": False, "game_ids": []})
    assert r.status_code == 422
    r = client.post("/api/admin/users", headers=admin, json={"username": "bob", "password": "Another-Pass1234", "role": "editor", "all_games": False, "game_ids": [999]})
    assert r.status_code == 422
    assert not [u for u in client.get("/api/admin/users", headers=admin).json() if u["username"] == "bob"]
    g = new_game(client, admin)
    r = client.post("/api/admin/users", headers=admin, json={"username": "adm2", "password": "Another-Pass1234", "role": "admin", "all_games": False, "game_ids": [g["id"]]})
    assert r.status_code == 201
    u = [u for u in client.get("/api/admin/users", headers=admin).json() if u["username"] == "adm2"][0]
    assert u["all_games"] is True      # admins are never restricted
    ana = scoped_user(client, admin, "ana", "editor", [g["id"]])
    ana_id = [u for u in client.get("/api/admin/users", headers=admin).json() if u["username"] == "ana"][0]["id"]
    client.put(f"/api/admin/users/{ana_id}", headers=admin, json={"all_games": True})
    assert len(client.get("/api/admin/games", headers=ana).json()["items"]) == 2


def test_per_game_branding_slides(client, admin):
    g = new_game(client, admin, overrides={"branding_use_shared_slides": False, "branding_hint_en": "Tap to guess"})
    add_published(client, admin, "Eyes one", g["id"])
    shared = client.get("/api/game/config").json()["slides"]
    assert shared                                   # seeded shared slides
    own = client.post("/api/admin/slides", headers=admin, json={"title_en": "Acme Sports", "game_id": g["id"]})
    assert own.status_code == 201
    cfg = client.get(f"/api/game/config?game={g['slug']}").json()
    assert [s["title_en"] for s in cfg["slides"]] == ["Acme Sports"]           # only its own, shared ones switched off
    assert cfg["settings"]["branding_hint_en"] == "Tap to guess"
    assert "Acme Sports" not in [s["title_en"] for s in client.get("/api/game/config").json()["slides"]]
    ana = scoped_user(client, admin, "ana", "editor", [g["id"]])
    assert client.post("/api/admin/slides", headers=ana, json={"title_en": "Mine", "game_id": g["id"]}).status_code == 201
    assert client.post("/api/admin/slides", headers=ana, json={"title_en": "Global"}).status_code == 403
    assert client.post("/api/admin/slides", headers=ana, json={"title_en": "Other", "game_id": 1}).status_code == 403
    assert {s["title_en"] for s in client.get("/api/admin/slides", headers=ana).json()} == {"Acme Sports", "Mine"}
    shared_id = client.get("/api/admin/slides", headers=admin).json()[0]["id"]
    assert client.delete(f"/api/admin/slides/{shared_id}", headers=ana).status_code in (403, 404)


def test_two_customers_play_different_games_at_once(client, admin):
    g = new_game(client, admin)
    mine = {add_published(client, admin, f"Eyes {i}", g["id"]) for i in range(3)}
    a = client.post("/api/game/sessions", json={"lang": "en"}).json()["session_id"]
    b = client.post("/api/game/sessions", json={"lang": "en", "game": g["slug"]}).json()["session_id"]
    qa = client.get(f"/api/game/sessions/{a}/question").json()
    qb = client.get(f"/api/game/sessions/{b}/question").json()
    assert qb["question"]["question_id"] in mine and qa["question"]["question_id"] not in mine
    # interleave answers: each session advances independently
    client.post(f"/api/game/sessions/{a}/timeout", json={"question_id": qa["question"]["question_id"]})
    assert client.get(f"/api/game/sessions/{b}/question").json()["index"] == 0
    assert client.get(f"/api/game/sessions/{a}/question").json()["index"] == 1


# ------------------------------------------------------------------ per-game access password
def test_game_password_gate(client, admin):
    g = new_game(client, admin, access_password="@123")
    assert g["has_password"] is True and "access_password" not in g and "access_password_hash" not in g
    add_published(client, admin, "Eyes one", g["id"])
    slug = g["slug"]
    # locked: no slides / questions info leak, can't start a session
    cfg = client.get(f"/api/game/config?game={slug}").json()
    assert cfg["locked"] is True and cfg["slides"] == [] and cfg["available_questions"] == {}
    assert client.post("/api/game/sessions", json={"lang": "en", "game": slug}).status_code == 401
    # the other game is unaffected (no password)
    assert client.post("/api/game/sessions", json={"lang": "en", "game": "football"}).status_code == 201
    # wrong password / right password
    assert client.post(f"/api/game/games/{slug}/unlock", json={"password": "nope"}).status_code == 403
    r = client.post(f"/api/game/games/{slug}/unlock", json={"password": "@123"})
    assert r.status_code == 200
    tok = {"X-Game-Token": r.json()["token"]}
    assert client.get(f"/api/game/config?game={slug}", headers=tok).json().get("locked") is None
    assert client.post("/api/game/sessions", json={"lang": "en", "game": slug}, headers=tok).status_code == 201
    # a token for this game does not open another locked game
    g2 = new_game(client, admin, name="Other", access_password="abcd")
    add_published(client, admin, "Other q", g2["id"])
    assert client.post("/api/game/sessions", json={"lang": "en", "game": g2["slug"]}, headers=tok).status_code == 401


def test_changing_or_clearing_password_revokes_tokens(client, admin):
    g = new_game(client, admin, access_password="first-pw")
    add_published(client, admin, "Eyes one", g["id"])
    tok = {"X-Game-Token": client.post(f"/api/game/games/{g['slug']}/unlock", json={"password": "first-pw"}).json()["token"]}
    assert client.post("/api/game/sessions", json={"lang": "en", "game": g["slug"]}, headers=tok).status_code == 201
    client.put(f"/api/admin/games/{g['id']}", headers=admin, json={**g, "access_password": "second-pw"})
    assert client.post("/api/game/sessions", json={"lang": "en", "game": g["slug"]}, headers=tok).status_code == 401
    assert client.post(f"/api/game/games/{g['slug']}/unlock", json={"password": "first-pw"}).status_code == 403
    # saving the form without a password keeps the existing one
    client.put(f"/api/admin/games/{g['id']}", headers=admin, json={**g, "name_en": "Renamed"})
    assert client.post(f"/api/game/games/{g['slug']}/unlock", json={"password": "second-pw"}).status_code == 200
    # clearing removes the gate
    client.put(f"/api/admin/games/{g['id']}", headers=admin, json={**g, "clear_access_password": True})
    assert client.post("/api/game/sessions", json={"lang": "en", "game": g["slug"]}).status_code == 201


def test_password_brute_force_throttled_and_min_length(client, admin):
    assert client.post("/api/admin/games", headers=admin, json={"name_en": "x", "access_password": "abc"}).status_code == 422
    g = new_game(client, admin, access_password="right-one")
    codes = [client.post(f"/api/game/games/{g['slug']}/unlock", json={"password": f"bad{i}"}).status_code for i in range(7)]
    assert codes[:5] == [403] * 5 and codes[5] == 429
    assert client.post(f"/api/game/games/{g['slug']}/unlock", json={"password": "right-one"}).status_code == 429


def test_admin_preview_bypasses_password_and_picker_flags_locked(client, admin):
    g = new_game(client, admin, access_password="@123")
    add_published(client, admin, "Eyes one", g["id"])
    assert client.get(f"/api/game/config?game={g['slug']}&preview=true", headers=admin).json().get("locked") is None
    assert client.get(f"/api/game/config?game={g['slug']}&preview=true").json()["locked"] is True
    items = {x["slug"]: x for x in client.get("/api/game/games").json()["items"]}
    assert items[g["slug"]]["locked"] is True and items["football"]["locked"] is False


def test_new_game_title_defaults_to_its_name(client, admin):
    g = new_game(client, admin)
    assert g["overrides"]["title_en"] == "Guess the Player" and g["overrides"]["title_ar"] == "خمن اللاعب"
