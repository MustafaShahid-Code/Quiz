"""Challenge mode: ask the player's name, play 3 questions, WIN with 2 correct, otherwise LOSE."""
from .test_games import add_published, new_game

CHALLENGE = {"questions_per_session": 3, "win_correct_needed": 2, "ask_player_name": True, "randomize_questions": False}


def challenge_game(client, admin, n_questions=3, **over):
    g = new_game(client, admin, overrides={**CHALLENGE, **over})
    for i in range(n_questions):
        add_published(client, admin, f"Who is player {i}", g["id"])
    return g


def play(client, g, plan, name="Sara"):
    """plan = list of booleans: answer each question right (True) or wrong (False). Returns (session_id, result)."""
    r = client.post("/api/game/sessions", json={"lang": "en", "game": g["slug"], "player_name": name})
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]
    for right in plan:
        q = client.get(f"/api/game/sessions/{sid}/question").json()["question"]
        # question n's options are "Who is player n-0..3" with option 0 correct (see q_payload)
        pick = next(o for o in q["options"] if o["label"].endswith("-0")) if right else next(o for o in q["options"] if not o["label"].endswith("-0"))
        a = client.post(f"/api/game/sessions/{sid}/answer", json={"question_id": q["question_id"], "option_id": pick["id"]}).json()
        assert a["correct"] is right
    return sid, client.get(f"/api/game/sessions/{sid}/result").json()


def test_name_required_cleaned_and_stored(client, admin):
    g = challenge_game(client, admin)
    for bad in (None, "", "   ", "​‮"):
        r = client.post("/api/game/sessions", json={"lang": "en", "game": g["slug"], "player_name": bad})
        assert r.status_code == 422
    r = client.post("/api/game/sessions", json={"lang": "en", "game": g["slug"], "player_name": "  Al‮   Mansoori\x00 " + "x" * 80})
    assert r.status_code == 201
    name = r.json()["player_name"]
    assert name.startswith("Al Mansoori") and len(name) <= 40 and "‮" not in name and "\x00" not in name
    assert r.json()["needed_to_win"] == 2 and r.json()["total"] == 3


def test_name_not_stored_when_game_does_not_ask(client):
    r = client.post("/api/game/sessions", json={"lang": "en", "player_name": "Nobody"})
    assert r.status_code == 201 and r.json()["player_name"] is None


def test_win_with_two_of_three(client, admin):
    g = challenge_game(client, admin)
    _, res = play(client, g, [True, False, True])
    assert res["outcome"] == "win" and res["player_name"] == "Sara" and res["correct"] == 2 and res["needed_to_win"] == 2 and res["total"] == 3


def test_win_with_three_of_three(client, admin):
    g = challenge_game(client, admin)
    assert play(client, g, [True, True, True])[1]["outcome"] == "win"


def test_lose_with_one_of_three(client, admin):
    g = challenge_game(client, admin)
    _, res = play(client, g, [False, True, False])
    assert res["outcome"] == "lose" and res["correct"] == 1


def test_lose_with_zero_and_outcome_missing_until_finished(client, admin):
    g = challenge_game(client, admin)
    r = client.post("/api/game/sessions", json={"lang": "en", "game": g["slug"], "player_name": "Omar"}).json()
    assert client.get(f"/api/game/sessions/{r['session_id']}/result").json()["outcome"] is None
    _, res = play(client, g, [False, False, False])
    assert res["outcome"] == "lose"


def test_needed_never_exceeds_questions_in_round(client, admin):
    g = challenge_game(client, admin, n_questions=1, questions_per_session=3, win_correct_needed=2)
    sid, res = play(client, g, [True])
    assert res["needed_to_win"] == 1 and res["outcome"] == "win"


def test_game_without_threshold_has_no_outcome(client, admin):
    g = challenge_game(client, admin, win_correct_needed=0)
    _, res = play(client, g, [True, True, True])
    assert res["outcome"] is None and res["needed_to_win"] == 0 and res["player_name"] == "Sara"


def test_admin_results_show_player_and_outcome(client, admin):
    g = challenge_game(client, admin)
    sid, _ = play(client, g, [True, True, False], name="Layla")
    play(client, g, [False, False, False], name="Khalid")
    items = client.get(f"/api/admin/sessions?game_id={g['id']}", headers=admin).json()["items"]
    by = {i["player_name"]: i["outcome"] for i in items}
    assert by == {"Layla": "win", "Khalid": "lose"}
    d = client.get(f"/api/admin/sessions/{sid}", headers=admin).json()
    assert d["player_name"] == "Layla" and d["outcome"] == "win"


def test_override_validation(client, admin):
    r = client.post("/api/admin/games", headers=admin, json={"name_en": "x", "overrides": {"win_correct_needed": 99}})
    assert r.status_code == 422
    r = client.post("/api/admin/games", headers=admin, json={"name_en": "y", "overrides": {"ask_player_name": "yes"}})
    assert r.status_code == 422


def test_timeouts_count_as_wrong_for_the_outcome(client, admin):
    g = challenge_game(client, admin)
    sid = client.post("/api/game/sessions", json={"lang": "en", "game": g["slug"], "player_name": "Noor"}).json()["session_id"]
    for right in (True, True, None):          # two right, then the clock runs out on the last one
        q = client.get(f"/api/game/sessions/{sid}/question").json()["question"]
        if right:
            pick = next(o for o in q["options"] if o["label"].endswith("-0"))
            client.post(f"/api/game/sessions/{sid}/answer", json={"question_id": q["question_id"], "option_id": pick["id"]})
        else:
            assert client.post(f"/api/game/sessions/{sid}/timeout", json={"question_id": q["question_id"]}).status_code == 200
    assert client.get(f"/api/game/sessions/{sid}/result").json()["outcome"] == "win"
    sid2 = client.post("/api/game/sessions", json={"lang": "en", "game": g["slug"], "player_name": "Noor"}).json()["session_id"]
    for _ in range(3):
        q = client.get(f"/api/game/sessions/{sid2}/question").json()["question"]
        client.post(f"/api/game/sessions/{sid2}/timeout", json={"question_id": q["question_id"]})
    assert client.get(f"/api/game/sessions/{sid2}/result").json()["outcome"] == "lose"
