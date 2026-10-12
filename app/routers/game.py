"""Public player-facing API, media serving and the input WebSocket."""
import hmac
import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import config, quiz, themes
from ..db import get_db, load_settings
from ..questions import LANGS
from ..schemas import AnswerIn, PoseEventIn, SessionStartIn
from .sensor import active_config_row

router = APIRouter(tags=["game"])
FILENAME = re.compile(r"^[a-f0-9]{32}\.[a-z0-9]{2,5}$")


def _active_slides(conn):
    now = datetime.now()
    out = []
    for r in conn.execute("SELECT * FROM brand_slides WHERE enabled=1 ORDER BY sort_order, id"):
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


@router.get("/api/game/config")
def game_config(request: Request, conn=Depends(get_db)):
    s = load_settings(conn)
    theme_row = conn.execute("SELECT * FROM themes WHERE is_active=1 ORDER BY id LIMIT 1").fetchone() or \
        conn.execute("SELECT * FROM themes ORDER BY id LIMIT 1").fetchone()
    from ..db import DEFAULT_THEME_TOKENS
    theme = themes.resolve_for_game(conn, theme_row) if theme_row else {**DEFAULT_THEME_TOKENS, "urls": {}, "id": 0, "name": "Default"}
    counts = {lg: len(quiz.eligible_questions(conn, lg)) for lg in LANGS}
    return {
        "settings": s, "theme": theme, "slides": _active_slides(conn) if s["branding_enabled"] else [],
        "available_questions": counts,
        "sensor": request.app.state.sensor.status(),
        "dev_mode": config.is_dev(),
    }


@router.post("/api/game/sessions", status_code=201)
def create_session(body: SessionStartIn, conn=Depends(get_db)):
    return quiz.start_session(conn, body.lang)


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
