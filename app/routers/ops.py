"""Operations: CSV export, prize claims, backup download, clear test results, system health."""
import csv
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from .. import config
from ..db import connect, get_db, now_iso
from ..quiz import format_claim_code, normalize_claim_code
from ..resultsq import clamp_tz, session_filters
from ..security import ensure_game, game_clause, require_admin, require_editor, require_viewer

router = APIRouter(prefix="/api/admin", tags=["operations"])
STARTED = time.time()
EXPORT_MAX_ROWS = 50_000


# ------------------------------------------------------------------ CSV export
def csv_safe(v):
    """Spreadsheet formula injection guard: a player may type a name such as =HYPERLINK(...)."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def local_time(iso: str | None, tz: int) -> str:
    if not iso:
        return ""
    try:
        return (datetime.fromisoformat(iso) + timedelta(minutes=tz)).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return iso


@router.get("/sessions-export.csv")
def export_sessions(kind: str = "rounds", game_id: int | None = None, lang: str = "", outcome: str = "", date_from: str = "", date_to: str = "",
                    q: str = "", tz: int = 0, user=Depends(require_viewer), conn=Depends(get_db)):
    """kind=rounds: one row per round (player, result, score). kind=answers: one row per answer. UTF-8 with BOM so Excel shows Arabic."""
    tzm = clamp_tz(tz)
    buf = io.StringIO(); w = csv.writer(buf)
    if kind == "answers":
        where, args = session_filters(conn, user, game_id, lang, outcome, date_from, date_to, q, tz, alias="s")
        w.writerow(["Round started (local)", "Game", "Player", "Language", "Round result", "Question #", "Question", "Answer given", "Correct", "Attempt", "Input", "Response ms"])
        rows = conn.execute(f"""SELECT s.started_at, (SELECT name_en FROM games g WHERE g.id=s.game_id) game, s.player_name, s.lang, s.outcome,
              r.question_text, r.option_label, r.is_correct, r.attempt_no, r.input_source, r.response_ms, s.id sid
              FROM game_responses r JOIN game_sessions s ON s.id=r.session_id {where}
              ORDER BY s.started_at DESC, r.id LIMIT ?""", args + [EXPORT_MAX_ROWS]).fetchall()
        n = {}
        for r in rows:
            n[r["sid"]] = n.get(r["sid"], 0) + 1
            w.writerow([local_time(r["started_at"], tzm), csv_safe(r["game"] or ""), csv_safe(r["player_name"] or ""), r["lang"], (r["outcome"] or "").upper(),
                        n[r["sid"]], csv_safe(r["question_text"] or ""), csv_safe(r["option_label"] or ""), "yes" if r["is_correct"] else "no", r["attempt_no"],
                        r["input_source"], r["response_ms"] if r["response_ms"] is not None else ""])
    else:
        where, args = session_filters(conn, user, game_id, lang, outcome, date_from, date_to, q, tz)
        w.writerow(["Started (local)", "Finished (local)", "Game", "Player", "Language", "Result", "Correct", "Questions", "Score", "Input", "Prize code", "Prize collected (local)", "Collected by"])
        rows = conn.execute(f"""SELECT started_at, finished_at, player_name, lang, outcome, correct_count, total_questions, score, claim_code, claimed_at, claimed_by,
              (SELECT name_en FROM games g WHERE g.id=game_sessions.game_id) game,
              (SELECT group_concat(DISTINCT input_source) FROM game_responses r WHERE r.session_id=game_sessions.id) sources
              FROM game_sessions {where} ORDER BY started_at DESC LIMIT ?""", args + [EXPORT_MAX_ROWS]).fetchall()
        for r in rows:
            w.writerow([local_time(r["started_at"], tzm), local_time(r["finished_at"], tzm), csv_safe(r["game"] or ""), csv_safe(r["player_name"] or ""), r["lang"],
                        (r["outcome"] or "").upper() if r["finished_at"] else "ABANDONED" if not r["outcome"] else "", r["correct_count"], r["total_questions"], r["score"],
                        r["sources"] or "", format_claim_code(r["claim_code"]) or "", local_time(r["claimed_at"], tzm), csv_safe(r["claimed_by"] or "")])
    data = ("﻿" + buf.getvalue()).encode("utf-8")
    fname = f"{'answers' if kind == 'answers' else 'rounds'}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.csv"
    return StreamingResponse(iter([data]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ------------------------------------------------------------------ prize claims
def _claim_row(conn, user, code: str):
    code = normalize_claim_code(code)
    r = conn.execute("""SELECT s.id, s.game_id, s.player_name, s.lang, s.started_at, s.finished_at, s.correct_count, s.total_questions, s.score, s.outcome,
        s.claim_code, s.claimed_at, s.claimed_by, (SELECT name_en FROM games g WHERE g.id=s.game_id) game_name
        FROM game_sessions s WHERE s.claim_code=?""", (code,)).fetchone() if len(code) >= 4 else None
    if not r:
        raise HTTPException(404, "No prize found for that code. Check the code and try again.")
    ensure_game(conn, user, r["game_id"])
    return r


def _claim_dict(r):
    return {"code": format_claim_code(r["claim_code"]), "session_id": r["id"], "player_name": r["player_name"], "game_id": r["game_id"], "game_name": r["game_name"],
            "won_at": r["finished_at"], "correct": r["correct_count"], "total": r["total_questions"], "score": r["score"], "lang": r["lang"],
            "claimed": bool(r["claimed_at"]), "claimed_at": r["claimed_at"], "claimed_by": r["claimed_by"]}


@router.get("/claims")
def list_claims(status: str = "all", game_id: int | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                user=Depends(require_viewer), conn=Depends(get_db)):
    where, args = session_filters(conn, user, game_id, claimed={"pending": "no", "collected": "yes"}.get(status, ""))
    where = (where + " AND " if where else "WHERE ") + "claim_code IS NOT NULL"
    total = conn.execute(f"SELECT COUNT(*) FROM game_sessions {where}", args).fetchone()[0]
    rows = conn.execute(f"""SELECT id, game_id, player_name, lang, started_at, finished_at, correct_count, total_questions, score, outcome, claim_code, claimed_at, claimed_by,
        (SELECT name_en FROM games g WHERE g.id=game_sessions.game_id) game_name
        FROM game_sessions {where} ORDER BY finished_at DESC LIMIT ? OFFSET ?""", args + [page_size, (page - 1) * page_size]).fetchall()
    pending = conn.execute(f"SELECT COUNT(*) FROM game_sessions {where} AND claimed_at IS NULL", args).fetchone()[0]
    return {"total": total, "pending": pending, "page": page, "page_size": page_size, "items": [_claim_dict(r) for r in rows]}


@router.get("/claims/{code}")
def get_claim(code: str, user=Depends(require_viewer), conn=Depends(get_db)):
    return _claim_dict(_claim_row(conn, user, code))


class RedeemIn(BaseModel):
    note: str = Field(default="", max_length=200)


@router.post("/claims/{code}/redeem")
def redeem_claim(code: str, body: RedeemIn, user=Depends(require_editor), conn=Depends(get_db)):
    r = _claim_row(conn, user, code)
    cur = conn.execute("UPDATE game_sessions SET claimed_at=?, claimed_by=? WHERE id=? AND claimed_at IS NULL", (now_iso(), user["username"], r["id"]))
    if cur.rowcount == 0:   # two staff members scanning the same code at once: only one wins
        again = _claim_row(conn, user, code)
        raise HTTPException(409, f"Already collected by {again['claimed_by']} at {again['claimed_at']}")
    return _claim_dict(_claim_row(conn, user, code))


@router.post("/claims/{code}/undo")
def undo_claim(code: str, user=Depends(require_admin), conn=Depends(get_db)):
    r = _claim_row(conn, user, code)
    conn.execute("UPDATE game_sessions SET claimed_at=NULL, claimed_by=NULL WHERE id=?", (r["id"],))
    return _claim_dict(_claim_row(conn, user, code))


# ------------------------------------------------------------------ clear test results
class ClearIn(BaseModel):
    confirm: str = Field(max_length=100)


@router.post("/games/{gid}/results/clear")
def clear_results(gid: int, body: ClearIn, user=Depends(require_admin), conn=Depends(get_db)):
    """Before a client event goes live: delete every played round of this game (test plays). Questions and settings stay."""
    g = conn.execute("SELECT * FROM games WHERE id=?", (gid,)).fetchone()
    if not g:
        raise HTTPException(404, "Game not found")
    if body.confirm.strip() != g["slug"]:
        raise HTTPException(422, f"Type the game's short name “{g['slug']}” to confirm")
    conn.execute("BEGIN IMMEDIATE")
    try:
        n = conn.execute("SELECT COUNT(*) FROM game_sessions WHERE game_id=?", (gid,)).fetchone()[0]
        conn.execute("DELETE FROM game_sessions WHERE game_id=?", (gid,))   # answers go with them (ON DELETE CASCADE)
        conn.execute("DELETE FROM question_serves WHERE game_id=?", (gid,))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK"); raise
    return {"deleted": n}


# ------------------------------------------------------------------ backup + system health
def _dir_size(p: Path) -> tuple[int, int]:
    n = size = 0
    if p.is_dir():
        for f in p.iterdir():
            if f.is_file():
                n += 1; size += f.stat().st_size
    return n, size


@router.get("/backup")
def download_backup(_=Depends(require_admin)):
    """One zip with a consistent copy of the database + every uploaded file. Keep it somewhere safe: it contains staff password hashes."""
    tmpdir = tempfile.mkdtemp(prefix="fqbackup-")
    snap = Path(tmpdir) / "fq.db"
    src = sqlite3.connect(config.db_path()); dst = sqlite3.connect(snap)
    try:
        src.backup(dst)          # safe while the game is running
    finally:
        dst.close(); src.close()
    zpath = Path(tmpdir) / "backup.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(snap, "fq.db")
        up = config.upload_dir()
        for f in sorted(up.iterdir()) if up.is_dir() else []:
            if f.is_file():
                z.write(f, f"uploads/{f.name}", compress_type=zipfile.ZIP_STORED)
        z.writestr("README.txt", "Football Quiz backup\nfq.db = database (SQLite)\nuploads/ = images and fonts\nRestore: stop the app, put fq.db and uploads/ back into the data folder.\n")
    name = f"fq-backup-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.zip"
    return FileResponse(zpath, media_type="application/zip", filename=name, background=BackgroundTask(shutil.rmtree, tmpdir, True))


@router.get("/system")
def system_status(_=Depends(require_admin), conn=Depends(get_db)):
    data = config.data_dir()
    n_up, size_up = _dir_size(config.upload_dir())
    try:
        disk = shutil.disk_usage(data)
        disk_free, disk_total = disk.free, disk.total
    except OSError:
        disk_free = disk_total = None
    bdir = Path(os.environ.get("FQ_BACKUP_DIR", "/var/backups/fq"))
    last_backup = None
    try:
        files = sorted(bdir.glob("*.tgz"), key=lambda f: f.stat().st_mtime) if bdir.is_dir() else []
        if files:
            last_backup = datetime.fromtimestamp(files[-1].stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    except OSError:
        pass
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="milliseconds")
    db = config.db_path()
    return {"uptime_seconds": int(time.time() - STARTED), "python": sys.version.split()[0], "env": config.env(),
            "db_bytes": db.stat().st_size if db.exists() else 0, "uploads": {"files": n_up, "bytes": size_up},
            "disk_free_bytes": disk_free, "disk_total_bytes": disk_total, "last_server_backup": last_backup,
            "rounds_24h": conn.execute("SELECT COUNT(*) FROM game_sessions WHERE started_at>=?", (since,)).fetchone()[0],
            "image_max_px": config.IMAGE_MAX_PX}
