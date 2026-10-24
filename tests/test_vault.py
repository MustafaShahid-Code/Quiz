"""Vault game type: the prize is attached to the question and revealed by the server only after a correct answer."""
from .test_games import new_game


def vault_q(text, prize_en="iPhone 18 Pro", prize_ar="آيفون 18 برو", game_id=None, correct=0, **extra):
    return {"text_en": text, "text_ar": text + " ع", "game_id": game_id, "prize_name_en": prize_en, "prize_name_ar": prize_ar,
            "prize_description_en": "Titanium, 512GB", "options": [{"label_en": f"{text}-{i}", "label_ar": f"{text}-{i} ع", "is_correct": i == correct} for i in range(4)], **extra}


def make_vault(client, admin, **kw):
    return new_game(client, admin, name="Vault Challenge", game_type="vault", **kw)


def publish(client, admin, payload):
    r = client.post("/api/admin/questions", headers=admin, json=payload)
    assert r.status_code == 201, r.text
    qid = r.json()["id"]
    return qid, client.post(f"/api/admin/questions/{qid}/status", headers=admin, json={"status": "published"})


def play_first(client, game):
    sid = client.post("/api/game/sessions", json={"lang": "en", "game": game["slug"]}).json()["session_id"]
    cur = client.get(f"/api/game/sessions/{sid}/question").json()
    return sid, cur


def correct_option(client, admin, qid):
    return client.get(f"/api/admin/questions/{qid}", headers=admin).json()["correct_option_id"]


def test_vault_defaults_and_type_listing(client, admin):
    g = make_vault(client, admin)
    assert g["game_type"] == "vault" and g["overrides"]["questions_per_session"] == 1
    assert {t["id"] for t in client.get("/api/admin/game-types", headers=admin).json()} == {"quiz", "vault"}
    assert client.post("/api/admin/games", headers=admin, json={"name_en": "x", "game_type": "bogus"}).status_code == 422


def test_vault_question_needs_prize_to_publish(client, admin):
    g = make_vault(client, admin)
    qid, r = publish(client, admin, vault_q("Which club?", prize_en="", game_id=g["id"]))
    assert r.status_code == 422 and "prize name in EN" in str(r.json())
    client.put(f"/api/admin/questions/{qid}", headers=admin, json=vault_q("Which club?", game_id=g["id"]))
    assert client.post(f"/api/admin/questions/{qid}/status", headers=admin, json={"status": "published"}).status_code == 200
    # an ordinary quiz game does not require a prize
    quiz = new_game(client, admin, name="Plain")
    _, r = publish(client, admin, vault_q("Plain q", prize_en="", prize_ar="", game_id=quiz["id"]))
    assert r.status_code == 200


def test_prize_is_revealed_only_after_correct_answer(client, admin):
    g = make_vault(client, admin)
    qid, _ = publish(client, admin, vault_q("Which club?", game_id=g["id"]))
    good = correct_option(client, admin, qid)
    sid, cur = play_first(client, g)
    assert "iPhone" not in str(cur) and "prize" not in str(cur)           # never sent with the question
    wrong = next(o["id"] for o in cur["question"]["options"] if o["id"] != good)
    r = client.post(f"/api/game/sessions/{sid}/answer", json={"question_id": qid, "option_id": wrong}).json()
    assert r["correct"] is False and "prize" not in r and "iPhone" not in str(r)
    sid, cur = play_first(client, g)
    r = client.post(f"/api/game/sessions/{sid}/answer", json={"question_id": qid, "option_id": good}).json()
    assert r["correct"] and r["prize"]["name"] == "iPhone 18 Pro" and r["prize"]["description"] == "Titanium, 512GB"
    res = client.get(f"/api/game/sessions/{sid}/result").json()
    assert [p["name"] for p in res["prizes"]] == ["iPhone 18 Pro"]


def test_each_question_has_its_own_prize_and_language(client, admin):
    g = make_vault(client, admin, overrides={"questions_per_session": 0, "randomize_questions": False})
    ids = {}
    for text, en, ar in (("Q1", "iPhone 18 Pro", "آيفون"), ("Q2", "PlayStation 6", "بلايستيشن"), ("Q3", "Gift card", "بطاقة")):
        ids[text], _ = publish(client, admin, vault_q(text, en, ar, game_id=g["id"]))
    sid = client.post("/api/game/sessions", json={"lang": "ar", "game": g["slug"]}).json()["session_id"]
    seen = []
    while True:
        cur = client.get(f"/api/game/sessions/{sid}/question").json()
        if cur["finished"]:
            break
        qid = cur["question"]["question_id"]
        r = client.post(f"/api/game/sessions/{sid}/answer", json={"question_id": qid, "option_id": correct_option(client, admin, qid)}).json()
        seen.append(r["prize"]["name"])
    assert sorted(seen) == sorted(["آيفون", "بلايستيشن", "بطاقة"])            # Arabic names for an Arabic round
    res = client.get(f"/api/game/sessions/{sid}/result").json()
    assert len(res["prizes"]) == 3
    rows = client.get(f"/api/admin/sessions/{sid}", headers=admin).json()["responses"]
    assert sorted(r["prize_name"] for r in rows) == sorted(seen)


def test_game_type_locked_once_questions_exist(client, admin):
    g = make_vault(client, admin)
    publish(client, admin, vault_q("Which club?", game_id=g["id"]))
    r = client.put(f"/api/admin/games/{g['id']}", headers=admin, json={**g, "game_type": "quiz"})
    assert r.status_code == 409
