"""Games (admin): each game has its own questions, optional theme and setting overrides."""
import json
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..db import GAME_OVERRIDE_KEYS, GAME_TYPES, get_db, now_iso
from ..security import hash_password
from ..security import allowed_games, ensure_game, require_admin, require_editor, require_viewer
from .settings import validate_settings

router = APIRouter(prefix="/api/admin", tags=["games"])
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class GameIn(BaseModel):
    slug: str = Field(default="", max_length=40)
    name_en: str = Field(default="", max_length=80)
    name_ar: str = Field(default="", max_length=80)
    description_en: str = Field(default="", max_length=200)
    description_ar: str = Field(default="", max_length=200)
    cover_asset_id: int | None = None
    theme_id: int | None = None
    overrides: dict = Field(default_factory=dict)
    game_type: str = "quiz"
    enabled: bool = True
    sort_order: int = 0
    access_password: str | None = Field(default=None, max_length=64)   # None = leave unchanged
    clear_access_password: bool = False


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def game_dict(conn, r) -> dict:
    n = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
    cover = conn.execute("SELECT filename FROM media_assets WHERE id=?", (r["cover_asset_id"],)).fetchone() if r["cover_asset_id"] else None
    return {
        "id": r["id"], "slug": r["slug"], "name_en": r["name_en"], "name_ar": r["name_ar"],
        "description_en": r["description_en"], "description_ar": r["description_ar"],
        "cover_asset_id": r["cover_asset_id"], "cover_url": f"/media/{cover['filename']}" if cover else None,
        "theme_id": r["theme_id"], "overrides": json.loads(r["overrides"] or "{}"),
        "has_password": bool(r["access_password_hash"]), "game_type": r["game_type"], "is_default": bool(r["is_default"]), "enabled": bool(r["enabled"]), "sort_order": r["sort_order"],
        "question_count": n("SELECT COUNT(*) FROM questions WHERE game_id=?", r["id"]),
        "published_count": n("SELECT COUNT(*) FROM questions WHERE game_id=? AND status='published' AND enabled=1", r["id"]),
        "session_count": n("SELECT COUNT(*) FROM game_sessions WHERE game_id=?", r["id"]),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }


def _clean(conn, b: GameIn, gid=None) -> dict:
    if not b.name_en.strip() and not b.name_ar.strip():
        raise HTTPException(422, "Give the game a name (English or Arabic)")
    slug = (b.slug.strip().lower() or _slugify(b.name_en) or f"game-{now_iso()[-6:]}")
    if not SLUG.match(slug):
        raise HTTPException(422, "Link name may only contain lowercase letters, numbers and dashes")
    dup = conn.execute("SELECT id FROM games WHERE slug=?", (slug,)).fetchone()
    if dup and dup["id"] != gid:
        raise HTTPException(409, f"A game with the link name “{slug}” already exists")
    if b.cover_asset_id is not None and not conn.execute("SELECT 1 FROM media_assets WHERE id=?", (b.cover_asset_id,)).fetchone():
        raise HTTPException(422, "Unknown cover image")
    if b.theme_id is not None and not conn.execute("SELECT 1 FROM themes WHERE id=?", (b.theme_id,)).fetchone():
        raise HTTPException(422, "Unknown theme")
    if b.game_type not in GAME_TYPES:
        raise HTTPException(422, f"Unknown game type {b.game_type!r}")
    if gid is not None:
        cur = conn.execute("SELECT game_type FROM games WHERE id=?", (gid,)).fetchone()
        if cur and cur["game_type"] != b.game_type and conn.execute("SELECT 1 FROM questions WHERE game_id=?", (gid,)).fetchone():
            raise HTTPException(409, "The game type can't be changed while the game has questions. Create a new game of that type instead.")
    if b.access_password is not None and b.access_password != "" and len(b.access_password) < 4:
        raise HTTPException(422, "The access password must be at least 4 characters")
    bad = [k for k in b.overrides if k not in GAME_OVERRIDE_KEYS]
    if bad:
        raise HTTPException(422, f"Setting(s) not allowed per game: {', '.join(bad)}")
    ov = validate_settings(conn, b.overrides)
    return {"slug": slug, "ov": json.dumps(ov, ensure_ascii=False)}


def _apply_password(conn, gid, b: GameIn):
    if b.clear_access_password:
        conn.execute("UPDATE games SET access_password_hash=NULL WHERE id=?", (gid,))
    elif b.access_password:
        conn.execute("UPDATE games SET access_password_hash=? WHERE id=?", (hash_password(b.access_password), gid))


@router.get("/game-types")
def list_game_types(_=Depends(require_viewer)):
    return [{"id": k, "label": v} for k, v in GAME_TYPES.items()]


@router.get("/games")
def list_games(user=Depends(require_viewer), conn=Depends(get_db)):
    ok = allowed_games(conn, user)
    rows = [r for r in conn.execute("SELECT * FROM games ORDER BY sort_order, id") if ok is None or r["id"] in ok]
    return {"items": [game_dict(conn, r) for r in rows], "override_keys": GAME_OVERRIDE_KEYS}


@router.post("/games", status_code=201)
def create_game(b: GameIn, _=Depends(require_admin), conn=Depends(get_db)):
    c = _clean(conn, b)
    ov = json.loads(c["ov"])
    if b.name_en.strip():            # the player screen shows the game's own name as its title unless the admin chose another
        ov.setdefault("title_en", b.name_en.strip())
    if b.name_ar.strip():
        ov.setdefault("title_ar", b.name_ar.strip())
    if b.game_type == "vault":       # sensible vault defaults, only where the admin did not choose
        ov.setdefault("questions_per_session", 1)
    c["ov"] = json.dumps(ov, ensure_ascii=False)
    ts = now_iso()
    cur = conn.execute(
        """INSERT INTO games(slug,name_en,name_ar,description_en,description_ar,cover_asset_id,theme_id,overrides,
           is_default,enabled,sort_order,created_at,updated_at,game_type) VALUES(?,?,?,?,?,?,?,?,0,?,?,?,?,?)""",
        (c["slug"], b.name_en.strip(), b.name_ar.strip(), b.description_en.strip(), b.description_ar.strip(),
         b.cover_asset_id, b.theme_id, c["ov"], int(b.enabled), b.sort_order, ts, ts, b.game_type))
    _apply_password(conn, cur.lastrowid, b)
    return game_dict(conn, conn.execute("SELECT * FROM games WHERE id=?", (cur.lastrowid,)).fetchone())


def _get(conn, gid):
    r = conn.execute("SELECT * FROM games WHERE id=?", (gid,)).fetchone()
    if not r:
        raise HTTPException(404, "Game not found")
    return r


@router.get("/games/{gid}")
def get_game(gid: int, user=Depends(require_viewer), conn=Depends(get_db)):
    ensure_game(conn, user, gid)
    return game_dict(conn, _get(conn, gid))


@router.put("/games/{gid}")
def update_game(gid: int, b: GameIn, _=Depends(require_admin), conn=Depends(get_db)):
    r = _get(conn, gid)
    if r["is_default"] and not b.enabled:
        raise HTTPException(409, "The default game cannot be disabled. Make another game the default first.")
    c = _clean(conn, b, gid)
    conn.execute(
        """UPDATE games SET slug=?,name_en=?,name_ar=?,description_en=?,description_ar=?,cover_asset_id=?,theme_id=?,
           overrides=?,enabled=?,sort_order=?,updated_at=? WHERE id=?""",
        (c["slug"], b.name_en.strip(), b.name_ar.strip(), b.description_en.strip(), b.description_ar.strip(),
         b.cover_asset_id, b.theme_id, c["ov"], int(b.enabled), b.sort_order, now_iso(), gid))
    _apply_password(conn, gid, b)
    return game_dict(conn, _get(conn, gid))


@router.post("/games/{gid}/make-default")
def make_default(gid: int, _=Depends(require_admin), conn=Depends(get_db)):
    r = _get(conn, gid)
    conn.execute("BEGIN")
    conn.execute("UPDATE games SET is_default=0")
    conn.execute("UPDATE games SET is_default=1, enabled=1, updated_at=? WHERE id=?", (now_iso(), r["id"]))
    conn.execute("COMMIT")
    return game_dict(conn, _get(conn, gid))


@router.delete("/games/{gid}")
def delete_game(gid: int, _=Depends(require_admin), conn=Depends(get_db)):
    r = _get(conn, gid)
    if r["is_default"]:
        raise HTTPException(409, "The default game cannot be deleted. Make another game the default first.")
    nq = conn.execute("SELECT COUNT(*) FROM questions WHERE game_id=?", (gid,)).fetchone()[0]
    if nq:
        raise HTTPException(409, f"This game still has {nq} question(s). Delete or move them first, or just disable the game.")
    ns = conn.execute("SELECT COUNT(*) FROM game_sessions WHERE game_id=?", (gid,)).fetchone()[0]
    if ns:
        raise HTTPException(409, f"This game has {ns} recorded session(s). Disable it instead to keep the results.")
    conn.execute("DELETE FROM games WHERE id=?", (gid,))
    return {"ok": True}
