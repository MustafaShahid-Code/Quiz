"""Public player-facing API, media serving and the input WebSocket."""
import hmac
import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import config, quiz, themes
from ..db import game_row, game_settings, get_db
from ..questions import LANGS
from ..schemas import AnswerIn, PoseEventIn, SessionStartIn
from ..security import (create_game_token, game_pw_throttle_key, game_token_valid, record_attempt, too_many_failures,
                         user_from_token, verify_password)
from .sensor import active_config_row

class UnlockIn(BaseModel):
    password: str = Field(max_length=128)


router = APIRouter(tags=["game"])
FILENAME = re.compile(r"^[a-f0-9]{32}\.[a-z0-9]{2,5}$")


def _active_slides(conn, game_id=None, include_shared=True):
    now = datetime.now()
    out = []
    for r in conn.execute("SELECT * FROM brand_slides WHERE enabled=1 ORDER BY sort_order, id"):
        if r["game_id"] is None:
            if not include_shared:
                continue
        elif r["game_id"] != game_id:
            continue
        try:
            if r["starts_at"] and datetime.fromisoformat(r["starts_at"]).replace(tzinfo=None) > now:
                continue
            if r["ends_at"] and datetime.fromisoformat(r["ends_at"]).replace(tzinfo=None) < now:
                continue
        except ValueError:
            continue
        fn = None
        if r["asset_id"]:
            a = conn.execute("SELECT filename FROM media_assets WHERE id=?", (r["asset_id"],)).fetchone()
            fn = a["filename"] if a else None
        out.append({"id": r["id"], "title_en": r["title_en"], "title_ar": r["title_ar"], "body_en": r["body_en"], "body_ar": r["body_ar"],
                    "image_url": f"/media/{fn}" if fn else None, "bg_color": r["bg_color"], "fit": r["fit"], "duration_ms": r["duration_ms"]})
    return out


def _access_ok(conn, g, request: Request, allow_admin=False) -> bool:
    """True when the game has no password, the caller holds a valid unlock token, or (previews only) is a signed-in admin."""
    if not g["access_password_hash"]:
        return True
    if game_token_valid(request.headers.get("x-game-token"), g):
        return True
    if allow_admin:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            try:
                user_from_token(auth[7:].strip(), conn)
                return True
            except HTTPException:
                return False
    return False


def _public_game(conn, g) -> dict:
    cover = conn.execute("SELECT filename FROM media_assets WHERE id=?", (g["cover_asset_id"],)).fetchone() if g["cover_asset_id"] else None
    s = game_settings(conn, g)
    return {"id": g["id"], "slug": g["slug"], "name_en": g["name_en"], "name_ar": g["name_ar"],
            "description_en": g["description_en"], "description_ar": g["description_ar"],
            "cover_url": f"/media/{cover['filename']}" if cover else None, "is_default": bool(g["is_default"]),
            "locked": bool(g["access_password_hash"]), "game_type": g["game_type"],
            "available_questions": {lg: len(quiz.eligible_questions(conn, lg, g["id"])) for lg in LANGS},
            "title_en": s["title_en"], "title_ar": s["title_ar"]}


def _playable_games(conn):
    """Enabled games that can actually be played (at least one eligible question in some language)."""
    out = []
    for g in conn.execute("SELECT * FROM games WHERE enabled=1 ORDER BY sort_order, id"):
        pg = _public_game(conn, g)
        if any(pg["available_questions"].values()):
            out.append(pg)
    return out


@router.get("/api/game/games")
def list_public_games(conn=Depends(get_db)):
    return {"items": _playable_games(conn)}


@router.post("/api/game/games/{slug}/unlock")
def unlock_game(slug: str, body: UnlockIn, conn=Depends(get_db)):
    g = game_row(conn, slug)
    if not g or not g["enabled"]:
        raise HTTPException(404, "Game not found or not available")
    if not g["access_password_hash"]:
        return {"token": None, "locked": False}
    key = game_pw_throttle_key(g)
    if too_many_failures(conn, key):
        raise HTTPException(429, "Too many wrong passwords. Please wait a few minutes and try again.")
    if not verify_password(body.password, g["access_password_hash"]):
        record_attempt(conn, key, None, False)
        raise HTTPException(403, "Wrong password")
    record_attempt(conn, key, None, True)
    return {"token": create_game_token(g), "locked": True}


@router.get("/api/game/config")
def game_config(request: Request, game: str | None = None, preview: bool = False, conn=Depends(get_db)):
    g = game_row(conn, game)
    if not g or not g["enabled"]:
        raise HTTPException(404, "Game not found or not available")
    s = game_settings(conn, g)
    if not _access_ok(conn, g, request, allow_admin=preview):
        # locked: only what the password screen needs (look + names). No slides, questions or rules.
        theme_row = (conn.execute("SELECT * FROM themes WHERE id=?", (g["theme_id"],)).fetchone() if g["theme_id"] else None) or \
            conn.execute("SELECT * FROM themes WHERE is_active=1 ORDER BY id LIMIT 1").fetchone() or \
            conn.execute("SELECT * FROM themes ORDER BY id LIMIT 1").fetchone()
        keys = ("title_en", "title_ar", "default_language", "enabled_languages", "idle_reset_seconds", "sound_enabled")
        pg = _public_game(conn, g)
        pg["available_questions"] = {}
        return {"locked": True, "settings": {k: s[k] for k in keys}, "game": pg, "games": _playable_games(conn),
                "theme": themes.resolve_for_game(conn, theme_row) if theme_row else None, "slides": [],
                "available_questions": {}, "sensor": request.app.state.sensor.status(), "dev_mode": config.is_dev()}
    theme_row = (conn.execute("SELECT * FROM themes WHERE id=?", (g["theme_id"],)).fetchone() if g["theme_id"] else None) or \
        conn.execute("SELECT * FROM themes WHERE is_active=1 ORDER BY id LIMIT 1").fetchone() or \
        conn.execute("SELECT * FROM themes ORDER BY id LIMIT 1").fetchone()
    from ..db import DEFAULT_THEME_TOKENS
    theme = themes.resolve_for_game(conn, theme_row) if theme_row else {**DEFAULT_THEME_TOKENS, "urls": {}, "id": 0, "name": "Default"}
    counts = {lg: len(quiz.eligible_questions(conn, lg, g["id"])) for lg in LANGS}
    return {
        "settings": s, "theme": theme, "slides": _active_slides(conn, g["id"], s["branding_use_shared_slides"]) if s["branding_enabled"] else [],
        "available_questions": counts, "game": _public_game(conn, g),
        "games": _playable_games(conn),
        "sensor": request.app.state.sensor.status(),
        "dev_mode": config.is_dev(),
    }


@router.post("/api/game/sessions", status_code=201)
def create_session(body: SessionStartIn, request: Request, conn=Depends(get_db)):
    g = game_row(conn, body.game)
    if g and not _access_ok(conn, g, request):
        raise HTTPException(401, "This game needs its access password")
    return quiz.start_session(conn, body.lang, body.game)


@router.get("/api/game/sessions/{sid}/question")
def current_question(sid: str, conn=Depends(get_db)):
    return quiz.get_current_question(conn, sid)


@router.post("/api/game/sessions/{sid}/answer")
def answer(sid: str, body: AnswerIn, request: Request, conn=Depends(get_db)):
    src = body.input_source
    if src in ("lidar", "simulated"):
        # a client may only claim a sensor source while the server really has a live sensor of that kind
        st = request.app.state.sensor.status()
        real = st["source"]
        if st["state"] not in ("ok", "stale") or real != src:
            src = "touch"
    return quiz.submit_answer(conn, sid, body.question_id, body.option_id, src, body.response_ms)


class TimeoutIn(BaseModel):
    question_id: int


@router.post("/api/game/sessions/{sid}/timeout")
def timeout(sid: str, body: TimeoutIn, conn=Depends(get_db)):
    return quiz.submit_timeout(conn, sid, body.question_id)


@router.get("/api/game/sessions/{sid}/result")
def result(sid: str, conn=Depends(get_db)):
    return quiz.get_result(conn, sid)


@router.get("/health")
def health(request: Request, conn=Depends(get_db)):
    conn.execute("SELECT 1")
    return {"ok": True, "sensor": request.app.state.sensor.status()["state"]}


# ------------------------------------------------------------------ media
@router.get("/media/{filename}")
def media(filename: str, conn=Depends(get_db)):
    if not FILENAME.match(filename):
        raise HTTPException(404)
    p = config.upload_dir() / filename
    row = conn.execute("SELECT mime FROM media_assets WHERE filename=?", (filename,)).fetchone()
    if not row or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type=row["mime"], headers={
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "public, max-age=3600"})


# ------------------------------------------------------------------ input channel
@router.websocket("/ws/input")
async def input_ws(ws: WebSocket):
    app = ws.app
    await app.state.input_hub.connect(ws, {"type": "status", **app.state.sensor.status()})
    try:
        while True:
            await ws.receive_text()  # clients only listen; messages are ignored
    except WebSocketDisconnect:
        pass
    finally:
        app.state.input_hub.disconnect(ws)


@router.post("/api/input/pose")
async def pose_event(body: PoseEventIn, request: Request, conn=Depends(get_db)):
    """Entry point for an external pose-estimation service (camera). Authenticated with the sensor input key."""
    key = request.headers.get("x-input-key", "")
    params = json.loads(active_config_row(conn)["params"] or "{}")
    if not key or not hmac.compare_digest(key, params.get("input_key", "")):
        raise HTTPException(401, "Invalid input key")
    await request.app.state.input_hub.broadcast({"type": "pose", "label": body.label, "confidence": body.confidence,
                                                 "source": "pose", "validated": True})
    return {"ok": True}
