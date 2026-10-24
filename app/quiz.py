"""Quiz engine. Runs on the trusted backend: the correct answer never leaves the server before the answer is final."""
import json
import random
import uuid
from datetime import datetime

from fastapi import HTTPException

from .db import game_row, game_settings, now_iso
from .questions import LANGS, get_options, languages_available, media_url, serialize_question

DUPLICATE_WINDOW_MS = 600


def eligible_questions(conn, lang: str, game_id: int):
    """Only questions that belong to this game: games never share questions."""
    rows = conn.execute("SELECT * FROM questions WHERE game_id=? AND status='published' AND enabled=1 ORDER BY sort_order, id",
                        (game_id,)).fetchall()
    out = []
    for q in rows:
        opts = get_options(conn, q["id"])
        if len([o for o in opts if o["is_correct"]]) != 1 or len(opts) < 2:
            continue  # defence in depth: never serve a malformed question
        if lang in languages_available(q, opts):
            out.append(q)
    return out


def _snapshot_question(conn, q, lang, randomize_options) -> dict:
    full = serialize_question(conn, q, include_correct=True)
    opts = list(full["options"])
    scheme = None
    if q["scheme_id"]:
        sch = conn.execute("SELECT * FROM interaction_schemes WHERE id=? AND enabled=1", (q["scheme_id"],)).fetchone()
        if sch:
            scheme = {"type": sch["scheme_type"], "config": json.loads(sch["config"] or "{}")}
    fixed_positions = bool(scheme)  # schemes address options by position, so keep the authored order
    if randomize_options and not fixed_positions:
        random.shuffle(opts)
    prize = None
    if q[f"prize_name_{lang}"].strip():
        prize = {"name": q[f"prize_name_{lang}"], "description": q[f"prize_description_{lang}"], "image_url": full["prize_image_url"]}
    return {
        "prize": prize,
        "question_id": q["id"], "uid": q["uid"], "version": q["version"], "difficulty": q["difficulty"],
        "text": full[f"text_{lang}"], "explanation": full[f"explanation_{lang}"],
        "image_url": full["image_url"], "reveal_url": full["reveal_url"],
        "character_name": full[f"character_name_{lang}"],
        "category": full[f"category_{lang}"],
        "scheme": scheme,
        "options": [{"id": o["id"], "label": o[f"label_{lang}"], "is_correct": o["is_correct"]} for o in opts],
    }


def start_session(conn, lang: str, game_key=None) -> dict:
    if lang not in LANGS:
        raise HTTPException(422, "Unsupported language")
    game = game_row(conn, game_key)
    if not game or not game["enabled"]:
        raise HTTPException(404, "Game not found or not available")
    s = game_settings(conn, game)
    if lang not in s["enabled_languages"]:
        raise HTTPException(422, "This language is not enabled")
    pool = eligible_questions(conn, lang, game["id"])
    if not pool:
        raise HTTPException(409, "No published questions are available for this game in this language yet")
    if s["randomize_questions"]:
        random.shuffle(pool)
    n = s["questions_per_session"]
    if n and n > 0:
        pool = pool[:n]
    snap = [_snapshot_question(conn, q, lang, s["randomize_options"]) for q in pool]
    sid = uuid.uuid4().hex
    conn.execute("INSERT INTO game_sessions(id,lang,started_at,total_questions,snapshot,settings_snapshot,game_id) VALUES(?,?,?,?,?,?,?)",
                 (sid, lang, now_iso(), len(snap), json.dumps(snap, ensure_ascii=False), json.dumps(s, ensure_ascii=False), game["id"]))
    return {"session_id": sid, "total": len(snap), "lang": lang, "game": game["slug"]}


def _session(conn, sid):
    row = conn.execute("SELECT * FROM game_sessions WHERE id=?", (sid,)).fetchone()
    if not row:
        raise HTTPException(404, "Session not found")
    return row


def public_question(row, snap, settings) -> dict:
    q = snap[row["current_index"]]
    return {
        "finished": False, "index": row["current_index"], "total": row["total_questions"], "score": row["score"],
        "question": {
            "question_id": q["question_id"], "text": q["text"], "image_url": q["image_url"],
            "character_name": None, "category": q["category"], "difficulty": q["difficulty"], "scheme": q["scheme"],
            "options": [{"id": o["id"], "label": o["label"]} for o in q["options"]],  # no is_correct
        },
        "retries_left": _retries_left(row["id"], q["question_id"], settings),
    }


def _retries_left(sid, qid, settings, conn=None):
    return settings.get("retries_per_question", 0)


def get_current_question(conn, sid: str) -> dict:
    row = _session(conn, sid)
    snap = json.loads(row["snapshot"])
    settings = json.loads(row["settings_snapshot"])
    if row["finished_at"] or row["current_index"] >= len(snap):
        return {"finished": True, "score": row["score"], "total": row["total_questions"]}
    out = public_question(row, snap, settings)
    attempts = conn.execute("SELECT COUNT(*) FROM game_responses WHERE session_id=? AND question_id=?",
                            (sid, snap[row["current_index"]]["question_id"])).fetchone()[0]
    out["retries_left"] = max(0, settings["retries_per_question"] - attempts)
    return out


def _parse_ts(s):
    return datetime.fromisoformat(s)


def _final_payload(q: dict, settings: dict, correct: bool) -> dict:
    """What the client may learn when a question closes. The full "reveal" picture (e.g. the whole player photo) is only ever sent
    for a correct answer; after a wrong one the player sees the question picture again, and the right answer/name/explanation are
    sent only if the game's "show the correct answer after a wrong answer" setting is on."""
    show_answer = correct or settings.get("show_correct_on_wrong", True)
    out = {"explanation": q["explanation"] if (settings["show_explanations"] and show_answer) else "",
           "reveal_url": (q["reveal_url"] or q["image_url"]) if correct else q["image_url"]}
    if show_answer:
        out["correct_option_id"] = next(o for o in q["options"] if o["is_correct"])["id"]
        out["character_name"] = q["character_name"]
    return out


def submit_answer(conn, sid: str, question_id: int, option_id: int, input_source: str, response_ms):
    conn.execute("BEGIN IMMEDIATE")  # serialise concurrent submissions for the session
    try:
        row = _session(conn, sid)
        snap = json.loads(row["snapshot"])
        settings = json.loads(row["settings_snapshot"])
        if row["finished_at"] or row["current_index"] >= len(snap):
            raise HTTPException(409, "Session already finished")
        q = snap[row["current_index"]]
        if q["question_id"] != question_id:
            raise HTTPException(409, "stale: that question is no longer active")
        opt = next((o for o in q["options"] if o["id"] == option_id), None)
        if opt is None:
            raise HTTPException(422, "Option does not belong to this question")

        prev = conn.execute("SELECT * FROM game_responses WHERE session_id=? AND question_id=? ORDER BY id", (sid, question_id)).fetchall()
        attempt_no = len(prev) + 1
        if prev:
            last = prev[-1]
            dt = (datetime.fromisoformat(now_iso()) - _parse_ts(last["answered_at"])).total_seconds() * 1000
            if last["option_id"] == option_id and dt < DUPLICATE_WINDOW_MS:
                raise HTTPException(409, "duplicate submission ignored")

        correct = bool(opt["is_correct"])
        prize = q.get("prize") if correct else None
        max_attempts = 1 + max(0, settings["retries_per_question"])
        final = correct or attempt_no >= max_attempts

        points = 0
        if correct:
            base = settings["points_correct"] * settings["difficulty_bonus"].get(q["difficulty"], 1.0)
            if attempt_no > 1:
                base *= settings["retry_points_fraction"]
            points = int(round(base))
        elif final:
            points = int(settings["points_incorrect"])

        new_score = max(0, row["score"] + points)
        correct_count = row["correct_count"] + (1 if correct else 0)
        conn.execute(
            """INSERT INTO game_responses(session_id,question_id,question_uid,question_version,question_text,option_id,option_label,
               is_correct,attempt_no,points,input_source,response_ms,answered_at,prize_name) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, question_id, q["uid"], q["version"], q["text"], option_id, opt["label"], int(correct), attempt_no, points,
             input_source, response_ms, now_iso(), prize["name"] if prize else None))

        idx = row["current_index"] + (1 if final else 0)
        finished = final and idx >= len(snap)
        conn.execute("UPDATE game_sessions SET score=?, correct_count=?, current_index=?, finished_at=? WHERE id=?",
                     (new_score, correct_count, idx, now_iso() if finished else None, sid))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    resp = {
        "correct": correct, "final": final, "can_retry": (not correct) and (not final),
        "score": new_score, "points": points, "attempt": attempt_no,
        "selected_option_id": option_id, "is_last": finished,
        "retries_left": max(0, max_attempts - attempt_no),
    }
    if correct and prize:
        resp["prize"] = prize          # the prize is only ever revealed by the server, after a correct answer
    if final:
        resp.update(_final_payload(q, settings, correct))
    return resp


def submit_timeout(conn, sid: str, question_id: int):
    """The player ran out of time without choosing: closes the question as incorrect (no retries)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = _session(conn, sid)
        snap = json.loads(row["snapshot"])
        settings = json.loads(row["settings_snapshot"])
        if row["finished_at"] or row["current_index"] >= len(snap):
            raise HTTPException(409, "Session already finished")
        q = snap[row["current_index"]]
        if q["question_id"] != question_id:
            raise HTTPException(409, "stale: that question is no longer active")
        if not settings.get("answer_timer_enabled"):
            raise HTTPException(409, "The answer timer is not enabled")
        if conn.execute("SELECT 1 FROM game_responses WHERE session_id=? AND question_id=? AND option_id IS NULL", (sid, question_id)).fetchone():
            raise HTTPException(409, "duplicate submission ignored")
        prev = conn.execute("SELECT COUNT(*) FROM game_responses WHERE session_id=? AND question_id=?", (sid, question_id)).fetchone()[0]
        points = int(settings["points_incorrect"])
        new_score = max(0, row["score"] + points)
        conn.execute(
            """INSERT INTO game_responses(session_id,question_id,question_uid,question_version,question_text,option_id,option_label,
               is_correct,attempt_no,points,input_source,response_ms,answered_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, question_id, q["uid"], q["version"], q["text"], None, "(no answer - time ran out)", 0, prev + 1, points,
             "timeout", settings["answer_time_limit_ms"], now_iso()))
        idx = row["current_index"] + 1
        finished = idx >= len(snap)
        conn.execute("UPDATE game_sessions SET score=?, current_index=?, finished_at=? WHERE id=?",
                     (new_score, idx, now_iso() if finished else None, sid))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {"correct": False, "final": True, "timed_out": True, "can_retry": False, "score": new_score, "points": points,
            "attempt": prev + 1, "selected_option_id": None, "is_last": finished, "retries_left": 0, **_final_payload(q, settings, False)}


def get_result(conn, sid: str) -> dict:
    row = _session(conn, sid)
    s = json.loads(row["settings_snapshot"])
    snap = json.loads(row["snapshot"])
    total = row["total_questions"]
    attempted = conn.execute("SELECT COUNT(DISTINCT question_id) FROM game_responses WHERE session_id=?", (sid,)).fetchone()[0]
    max_score = int(sum(round(s["points_correct"] * s["difficulty_bonus"].get(q["difficulty"], 1.0)) for q in snap))
    pct = round(100 * row["correct_count"] / total) if total else 0
    tier = "perfect" if total and row["correct_count"] == total else ("high" if pct >= s["high_score_percent"] else "normal")
    won = {r["question_id"] for r in conn.execute("SELECT question_id FROM game_responses WHERE session_id=? AND is_correct=1", (sid,))}
    prizes = [q["prize"] for q in snap if q["question_id"] in won and q.get("prize")]
    return {"prizes": prizes, "finished": bool(row["finished_at"]), "score": row["score"], "max_score": max_score, "correct": row["correct_count"],
            "attempted": attempted, "total": total, "percent": pct, "tier": tier, "lang": row["lang"]}
