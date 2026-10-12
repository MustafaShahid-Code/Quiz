"""Game settings, statistics and results (admin)."""
from fastapi import APIRouter, Depends, HTTPException, Query

from ..db import DEFAULT_SETTINGS, get_db, load_settings, save_settings
from ..schemas import HEX, SettingsIn
from ..security import require_admin, require_editor, require_viewer

router = APIRouter(prefix="/api/admin", tags=["settings"])

RANGES = {
    "questions_per_session": (0, 50), "retries_per_question": (0, 3), "retry_points_fraction": (0, 1),
    "points_correct": (0, 1000), "points_incorrect": (-1000, 1000), "high_score_percent": (1, 100),
    "auto_advance_delay_ms": (1000, 30000), "confirm_delay_ms": (500, 15000), "answer_time_limit_ms": (2000, 120000), "idle_reset_seconds": (0, 3600),
    "branding_default_duration_ms": (1500, 60000),
}
TEXT_LIMITS = {"client_name": 80, "admin_product_name": 80}


def validate_settings(conn, values: dict) -> dict:
    out = {}
    for k, v in values.items():
        if k not in DEFAULT_SETTINGS:
            raise HTTPException(422, f"Unknown setting {k!r}")
        d = DEFAULT_SETTINGS[k]
        if isinstance(d, bool):
            if not isinstance(v, bool):
                raise HTTPException(422, f"{k} must be true or false")
        elif isinstance(d, (int, float)) and k != "retry_points_fraction":
            if not isinstance(v, int) or isinstance(v, bool):
                raise HTTPException(422, f"{k} must be a whole number")
        elif k == "retry_points_fraction":
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise HTTPException(422, f"{k} must be a number")
        elif isinstance(d, str):
            if not isinstance(v, str):
                raise HTTPException(422, f"{k} must be text")
            if len(v) > TEXT_LIMITS.get(k, 300):
                raise HTTPException(422, f"{k} is too long")
        elif isinstance(d, list):
            if not isinstance(v, list) or not all(isinstance(x, str) and 0 < len(x) <= 120 for x in v) or len(v) > 10:
                raise HTTPException(422, f"{k} must be a list of up to 10 short texts")
        if k in RANGES:
            lo, hi = RANGES[k]
            if not lo <= v <= hi:
                raise HTTPException(422, f"{k} must be between {lo} and {hi}")
        if k in ("admin_logo_asset_id", "favicon_asset_id", "login_bg_asset_id") and v is not None:
            if not isinstance(v, int) or not conn.execute("SELECT 1 FROM media_assets WHERE id=?", (v,)).fetchone():
                raise HTTPException(422, f"{k}: unknown asset")
        if k in ("admin_primary_color", "login_color_2") and not HEX.match(v):
            raise HTTPException(422, f"{k} must be a hex colour")
        if k == "login_layout" and v not in ("split", "centered"):
            raise HTTPException(422, "login_layout must be split or centered")
        if k == "default_language" and v not in ("en", "ar"):
            raise HTTPException(422, "default_language must be en or ar")
        if k == "enabled_languages":
            if not isinstance(v, list) or not v or any(x not in ("en", "ar") for x in v):
                raise HTTPException(422, "enabled_languages must be a non-empty list of en/ar")
        if k == "difficulty_bonus":
            if not isinstance(v, dict) or set(v) != {"easy", "medium", "hard"} or any(
                    not isinstance(x, (int, float)) or isinstance(x, bool) or not 0 <= x <= 10 for x in v.values()):
                raise HTTPException(422, "difficulty_bonus needs easy/medium/hard multipliers between 0 and 10")
        out[k] = v
    return out


@router.get("/settings")
def get_settings(_=Depends(require_viewer), conn=Depends(get_db)):
    return load_settings(conn)


@router.put("/settings")
def put_settings(body: SettingsIn, _=Depends(require_admin), conn=Depends(get_db)):
    clean = validate_settings(conn, body.values)
    current = load_settings(conn)
    merged = {**current, **clean}
    if merged["default_language"] not in merged["enabled_languages"]:
        raise HTTPException(422, "default_language must be one of the enabled languages")
    save_settings(conn, clean)
    return load_settings(conn)


# ------------------------------------------------------------------ statistics & results
@router.get("/stats")
def stats(_=Depends(require_viewer), conn=Depends(get_db)):
    q = {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) n FROM questions GROUP BY status")}
    sess = conn.execute("SELECT COUNT(*) n, SUM(finished_at IS NOT NULL) fin FROM game_sessions").fetchone()
    fin = conn.execute("""SELECT AVG(100.0*correct_count/NULLIF(total_questions,0)) pct, AVG(score) avg_score
                          FROM game_sessions WHERE finished_at IS NOT NULL""").fetchone()
    resp = conn.execute("SELECT COUNT(*) n, SUM(is_correct) ok FROM game_responses").fetchone()
    by_source = {r["input_source"]: r["n"] for r in conn.execute("SELECT input_source, COUNT(*) n FROM game_responses GROUP BY input_source")}
    hardest = [dict(r) for r in conn.execute("""
        SELECT question_id, question_text, COUNT(*) answers, ROUND(100.0*SUM(is_correct)/COUNT(*),0) pct_correct
        FROM game_responses WHERE attempt_no=1 GROUP BY question_uid HAVING COUNT(*)>=3
        ORDER BY pct_correct ASC, answers DESC LIMIT 5""")]
    per_day = [dict(r) for r in conn.execute("""
        SELECT substr(started_at,1,10) day, COUNT(*) sessions FROM game_sessions
        GROUP BY day ORDER BY day DESC LIMIT 14""")][::-1]
    return {
        "questions": {"published": q.get("published", 0), "draft": q.get("draft", 0), "unpublished": q.get("unpublished", 0),
                      "total": sum(q.values())},
        "sessions": {"total": sess["n"] or 0, "finished": int(sess["fin"] or 0)},
        "avg_percent_correct": round(fin["pct"], 1) if fin["pct"] is not None else None,
        "avg_score": round(fin["avg_score"], 1) if fin["avg_score"] is not None else None,
        "responses": {"total": resp["n"] or 0, "correct": int(resp["ok"] or 0)},
        "input_sources": by_source, "hardest_questions": hardest, "sessions_per_day": per_day,
    }


@router.get("/sessions")
def list_sessions(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), lang: str = "",
                  _=Depends(require_viewer), conn=Depends(get_db)):
    where, args = "", []
    if lang in ("en", "ar"):
        where, args = "WHERE lang=?", [lang]
    total = conn.execute(f"SELECT COUNT(*) FROM game_sessions {where}", args).fetchone()[0]
    rows = conn.execute(f"""SELECT id, lang, started_at, finished_at, score, correct_count, total_questions,
        (SELECT group_concat(DISTINCT input_source) FROM game_responses r WHERE r.session_id=game_sessions.id) sources
        FROM game_sessions {where} ORDER BY started_at DESC LIMIT ? OFFSET ?""", args + [page_size, (page - 1) * page_size]).fetchall()
    return {"total": total, "page": page, "page_size": page_size, "items": [dict(r) for r in rows]}


@router.get("/sessions/{sid}")
def session_detail(sid: str, _=Depends(require_viewer), conn=Depends(get_db)):
    s = conn.execute("SELECT id, lang, started_at, finished_at, score, correct_count, total_questions FROM game_sessions WHERE id=?", (sid,)).fetchone()
    if not s:
        raise HTTPException(404, "Session not found")
    resp = [dict(r) for r in conn.execute("SELECT * FROM game_responses WHERE session_id=? ORDER BY id", (sid,))]
    return {**dict(s), "responses": resp}
