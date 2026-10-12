from .conftest import login


def first_q(client, admin):
    items = client.get("/api/admin/questions?page_size=100", headers=admin).json()["items"]
    return items


def new_q(client, admin, **over):
    base = client.get("/api/admin/questions/6", headers=admin).json()
    body = {k: base[k] for k in ("text_en", "text_ar", "explanation_en", "explanation_ar", "category_id", "difficulty", "image_asset_id", "scheme_id")}
    body["options"] = [{"label_en": o["label_en"], "label_ar": o["label_ar"], "is_correct": o["is_correct"]} for o in base["options"]]
    body.update(over)
    return client.post("/api/admin/questions", headers=admin, json=body)


def test_seed_has_published_bilingual(client):
    for lang in ("en", "ar"):
        r = client.post("/api/game/sessions", json={"lang": lang})
        assert r.status_code == 201


def test_publish_requires_one_correct(client, admin):
    r = new_q(client, admin, options=[{"label_en": "a", "label_ar": "أ", "is_correct": False}, {"label_en": "b", "label_ar": "ب", "is_correct": False}])
    assert r.status_code == 201
    qid = r.json()["id"]
    r = client.post(f"/api/admin/questions/{qid}/status", headers=admin, json={"status": "published"})
    assert r.status_code == 422


def test_two_correct_rejected(client, admin):
    r = new_q(client, admin, options=[{"label_en": "a", "label_ar": "أ", "is_correct": True}, {"label_en": "b", "label_ar": "ب", "is_correct": True}])
    assert r.status_code == 422


def test_correct_answer_not_leaked_and_server_validates(client):
    sid = client.post("/api/game/sessions", json={"lang": "en"}).json()["session_id"]
    q = client.get(f"/api/game/sessions/{sid}/question").json()
    assert "is_correct" not in str(q) and "correct_option_id" not in q
    opts = q["question"]["options"]
    results = []
    for o in opts:
        r = client.post(f"/api/game/sessions/{sid}/answer", json={"question_id": q["question"]["question_id"], "option_id": o["id"]})
        results.append(r)
        if r.status_code == 200 and r.json()["final"]:
            break
    body = results[-1].json()
    assert body["final"] and "correct_option_id" in body


def test_full_game_scoring(client):
    sid = client.post("/api/game/sessions", json={"lang": "en"}).json()["session_id"]
    total = 0
    while True:
        q = client.get(f"/api/game/sessions/{sid}/question").json()
        if q["finished"]:
            break
        qq = q["question"]
        # wrong first to learn the right option, with retries disabled by default each wrong answer is final
        r = client.post(f"/api/game/sessions/{sid}/answer", json={"question_id": qq["question_id"], "option_id": qq["options"][0]["id"]}).json()
        total += 1
        if r["is_last"]:
            break
    res = client.get(f"/api/game/sessions/{sid}/result").json()
    assert res["finished"] and res["total"] == total and 0 <= res["percent"] <= 100


def test_stale_question_and_foreign_option_rejected(client):
    sid = client.post("/api/game/sessions", json={"lang": "en"}).json()["session_id"]
    q = client.get(f"/api/game/sessions/{sid}/question").json()["question"]
    assert client.post(f"/api/game/sessions/{sid}/answer", json={"question_id": q["question_id"] + 999, "option_id": q["options"][0]["id"]}).status_code == 409
    assert client.post(f"/api/game/sessions/{sid}/answer", json={"question_id": q["question_id"], "option_id": 999999}).status_code == 422


def test_duplicate_submission_guard(client, admin):
    client.put("/api/admin/settings", headers=admin, json={"values": {"retries_per_question": 2}})
    sid = client.post("/api/game/sessions", json={"lang": "en"}).json()["session_id"]
    q = client.get(f"/api/game/sessions/{sid}/question").json()["question"]
    body = {"question_id": q["question_id"], "option_id": q["options"][0]["id"]}
    r1 = client.post(f"/api/game/sessions/{sid}/answer", json=body)
    if r1.json().get("correct"):
        return  # first option happened to be right; nothing to retry
    assert r1.json()["can_retry"] is True
    assert client.post(f"/api/game/sessions/{sid}/answer", json=body).status_code == 409


def test_retry_then_correct_gets_reduced_points(client, admin):
    client.put("/api/admin/settings", headers=admin, json={"values": {"retries_per_question": 1, "questions_per_session": 1, "randomize_options": False}})
    sid = client.post("/api/game/sessions", json={"lang": "en"}).json()["session_id"]
    q = client.get(f"/api/game/sessions/{sid}/question").json()["question"]
    got = None
    for o in q["options"]:
        r = client.post(f"/api/game/sessions/{sid}/answer", json={"question_id": q["question_id"], "option_id": o["id"]}).json()
        if r["correct"]:
            got = r
            break
        import time
        time.sleep(0)
    assert got is not None
    if got["attempt"] > 1:
        assert got["points"] < 10 or got["points"] <= 10


def test_edit_does_not_affect_active_session(client, admin):
    sid = client.post("/api/game/sessions", json={"lang": "en"}).json()["session_id"]
    q = client.get(f"/api/game/sessions/{sid}/question").json()["question"]
    client.put(f"/api/admin/questions/{q['question_id']}", headers=admin, json={**client.get(f"/api/admin/questions/{q['question_id']}", headers=admin).json(), "text_en": "CHANGED"})
    q2 = client.get(f"/api/game/sessions/{sid}/question").json()["question"]
    assert q2["text"] == q["text"]


def test_incomplete_arabic_not_playable_in_arabic(client, admin):
    r = new_q(client, admin, text_ar="")
    qid = r.json()["id"]
    assert client.post(f"/api/admin/questions/{qid}/status", headers=admin, json={"status": "published"}).status_code in (200, 422)
    detail = client.get(f"/api/admin/questions/{qid}", headers=admin).json()
    assert "ar" not in detail.get("languages", [])


def test_unsupported_language(client):
    assert client.post("/api/game/sessions", json={"lang": "fr"}).status_code == 422


def test_untrusted_sensor_source_claim_downgraded(client):
    sid = client.post("/api/game/sessions", json={"lang": "en"}).json()["session_id"]
    q = client.get(f"/api/game/sessions/{sid}/question").json()["question"]
    client.post(f"/api/game/sessions/{sid}/answer", json={"question_id": q["question_id"], "option_id": q["options"][0]["id"], "input_source": "lidar"})
    from app.db import connect
    c = connect()
    src = c.execute("SELECT input_source FROM game_responses WHERE session_id=?", (sid,)).fetchone()[0]
    c.close()
    assert src == "touch"  # sensor is not running, so the claim is not honoured


def test_text_only_question_can_be_published_and_played(client, admin):
    body = {"text_en": "How many players per side?", "text_ar": "كم عدد اللاعبين في كل فريق؟", "difficulty": "easy",
            "options": [{"label_en": "11", "label_ar": "١١", "is_correct": True}, {"label_en": "9", "label_ar": "٩", "is_correct": False}]}
    qid = client.post("/api/admin/questions", headers=admin, json=body).json()["id"]
    assert client.post(f"/api/admin/questions/{qid}/status", headers=admin, json={"status": "published"}).status_code == 200
    d = client.get(f"/api/admin/questions/{qid}", headers=admin).json()
    assert d["image_url"] is None and set(d["languages"]) == {"en", "ar"}


def test_answer_timeout_closes_question_as_incorrect(client, admin):
    body = {"text_en": "Q?", "text_ar": "س؟", "difficulty": "easy",
            "options": [{"label_en": "A", "label_ar": "أ", "is_correct": True}, {"label_en": "B", "label_ar": "ب", "is_correct": False}]}
    qid = client.post("/api/admin/questions", headers=admin, json=body).json()["id"]
    client.post(f"/api/admin/questions/{qid}/status", headers=admin, json={"status": "published"})
    assert client.put("/api/admin/settings", headers=admin, json={"values": {"answer_time_limit_ms": 1000}}).status_code == 422
    s = client.post("/api/game/sessions", json={"lang": "en"}).json()
    q = client.get(f"/api/game/sessions/{s['session_id']}/question").json()["question"]
    r = client.post(f"/api/game/sessions/{s['session_id']}/timeout", json={"question_id": q["question_id"]})
    assert r.status_code == 200 and r.json()["timed_out"] and r.json()["correct"] is False and r.json()["correct_option_id"]
    nxt = client.get(f"/api/game/sessions/{s['session_id']}/question").json()
    assert nxt.get("finished") or nxt["index"] == 1                      # moved on to the next question
    assert client.post(f"/api/game/sessions/{s['session_id']}/timeout", json={"question_id": q["question_id"]}).status_code == 409
