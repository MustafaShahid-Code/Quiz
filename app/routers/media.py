"""Media assets, branding slides and white-label themes (admin)."""
import json
import re
import uuid
from datetime import datetime, timezone
from io import BytesIO

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from PIL import Image

from .. import config, themes
from ..db import DEFAULT_THEME_TOKENS, get_db, load_settings, now_iso, resolve_theme_tokens
from ..questions import media_url
from ..schemas import SlideIn, ThemeIn
from ..security import allowed_games, ensure_game, game_clause, require_admin, require_editor, require_viewer

router = APIRouter(prefix="/api/admin", tags=["media"])

IMAGE_TYPES = {"PNG": ("image/png", "png"), "JPEG": ("image/jpeg", "jpg"), "WEBP": ("image/webp", "webp"), "GIF": ("image/gif", "gif")}
SVG_FORBIDDEN = re.compile(rb"<\s*script|<\s*foreignObject|\son\w+\s*=|javascript:|<\s*iframe|<\s*embed|<\s*object|<!ENTITY|xlink:href\s*=\s*[\"']\s*(?!#)", re.I)
FONT_MAGIC = {b"wOF2": ("font/woff2", "woff2"), b"wOFF": ("font/woff", "woff"), b"OTTO": ("font/otf", "otf"), b"\x00\x01\x00\x00": ("font/ttf", "ttf"), b"true": ("font/ttf", "ttf")}


def detect_and_validate(data: bytes) -> dict:
    """Never trust the client's content type: sniff the bytes."""
    if len(data) == 0:
        raise HTTPException(422, "Empty file")
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large (max {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB)")
    head = data[:4]
    if head in FONT_MAGIC:
        mime, ext = FONT_MAGIC[head]
        return {"mime": mime, "ext": ext, "width": None, "height": None, "kind": "font"}
    stripped = data.lstrip()[:512].lower()
    if stripped.startswith(b"<svg") or (stripped.startswith(b"<?xml") and b"<svg" in data[:2048].lower()):
        if SVG_FORBIDDEN.search(data):
            raise HTTPException(422, "This SVG contains scripts or external references and was rejected for safety")
        return {"mime": "image/svg+xml", "ext": "svg", "width": None, "height": None, "kind": "image"}
    try:
        im = Image.open(BytesIO(data))
        fmt = im.format
        im.verify()
        im = Image.open(BytesIO(data))
        w, h = im.size
    except Exception:
        raise HTTPException(422, "Unsupported or corrupt file. Use PNG, JPEG, WebP, GIF, SVG or a WOFF2/WOFF/TTF/OTF font.")
    if fmt not in IMAGE_TYPES:
        raise HTTPException(422, f"Unsupported image format {fmt}")
    if w * h > 40_000_000:
        raise HTTPException(422, "Image dimensions are too large")
    mime, ext = IMAGE_TYPES[fmt]
    return {"mime": mime, "ext": ext, "width": w, "height": h, "kind": "image"}


def store_asset(conn, data: bytes, original_name: str | None) -> int:
    info = detect_and_validate(data)
    fname = f"{uuid.uuid4().hex}.{info['ext']}"
    (config.upload_dir() / fname).write_bytes(data)
    cur = conn.execute("INSERT INTO media_assets(filename,original_name,mime,size_bytes,width,height,created_at) VALUES(?,?,?,?,?,?,?)",
                       (fname, (original_name or "")[:200], info["mime"], len(data), info["width"], info["height"], now_iso()))
    return cur.lastrowid


def asset_dict(r):
    return {"id": r["id"], "url": f"/media/{r['filename']}", "original_name": r["original_name"], "mime": r["mime"],
            "size_bytes": r["size_bytes"], "width": r["width"], "height": r["height"], "created_at": r["created_at"],
            "kind": "font" if r["mime"].startswith("font/") else "image"}


def asset_usage(conn, aid: int) -> list[str]:
    use = []
    for label, sql in (("question image", "SELECT id FROM questions WHERE image_asset_id=?"),
                       ("question reveal image", "SELECT id FROM questions WHERE reveal_asset_id=?"),
                       ("prize image", "SELECT id FROM questions WHERE prize_asset_id=?"),
                       ("character image", "SELECT id FROM characters WHERE asset_id=? OR reveal_asset_id=?"),
                       ("branding slide", "SELECT id FROM brand_slides WHERE asset_id=?"),
                       ("game cover", "SELECT id FROM games WHERE cover_asset_id=?")):
        n = len(conn.execute(sql, (aid,) * sql.count("?")).fetchall())
        if n:
            use.append(f"{n} {label}{'s' if n > 1 else ''}")
    for t in conn.execute("SELECT id, name, tokens FROM themes"):
        tk = resolve_theme_tokens(t["tokens"])
        if aid in list(tk["assets"].values()) + [tk["fonts"]["font_asset_id"]]:
            use.append(f"theme “{t['name']}”")
    s = load_settings(conn)
    if aid in (s.get("admin_logo_asset_id"), s.get("favicon_asset_id"), s.get("login_bg_asset_id")):
        use.append("platform branding")
    return use


@router.get("/assets")
def list_assets(kind: str = "", _=Depends(require_viewer), conn=Depends(get_db)):
    rows = [asset_dict(r) for r in conn.execute("SELECT * FROM media_assets ORDER BY id DESC")]
    if kind:
        rows = [r for r in rows if r["kind"] == kind]
    for r in rows:
        r["in_use"] = bool(asset_usage(conn, r["id"]))
    return rows


@router.post("/assets", status_code=201)
async def upload_asset(file: UploadFile = File(...), _=Depends(require_editor), conn=Depends(get_db)):
    data = await file.read(config.MAX_UPLOAD_BYTES + 1)
    aid = store_asset(conn, data, file.filename)
    return asset_dict(conn.execute("SELECT * FROM media_assets WHERE id=?", (aid,)).fetchone())


@router.put("/assets/{aid}/replace")
async def replace_asset(aid: int, file: UploadFile = File(...), _=Depends(require_editor), conn=Depends(get_db)):
    old = conn.execute("SELECT * FROM media_assets WHERE id=?", (aid,)).fetchone()
    if not old:
        raise HTTPException(404, "Asset not found")
    data = await file.read(config.MAX_UPLOAD_BYTES + 1)
    info = detect_and_validate(data)
    fname = f"{uuid.uuid4().hex}.{info['ext']}"
    (config.upload_dir() / fname).write_bytes(data)
    conn.execute("UPDATE media_assets SET filename=?,original_name=?,mime=?,size_bytes=?,width=?,height=? WHERE id=?",
                 (fname, (file.filename or "")[:200], info["mime"], len(data), info["width"], info["height"], aid))
    try:
        (config.upload_dir() / old["filename"]).unlink(missing_ok=True)
    except OSError:
        pass
    return asset_dict(conn.execute("SELECT * FROM media_assets WHERE id=?", (aid,)).fetchone())


@router.delete("/assets/{aid}")
def delete_asset(aid: int, _=Depends(require_editor), conn=Depends(get_db)):
    r = conn.execute("SELECT * FROM media_assets WHERE id=?", (aid,)).fetchone()
    if not r:
        raise HTTPException(404, "Asset not found")
    use = asset_usage(conn, aid)
    if use:
        raise HTTPException(409, "This asset is still in use by: " + ", ".join(use))
    conn.execute("DELETE FROM media_assets WHERE id=?", (aid,))
    (config.upload_dir() / r["filename"]).unlink(missing_ok=True)
    return {"ok": True}


# ------------------------------------------------------------------ branding slides
def slide_dict(conn, r):
    d = dict(r)
    d["enabled"] = bool(d["enabled"])
    d["image_url"] = media_url(conn, r["asset_id"])
    return d


def _check_slide(conn, b: SlideIn):
    if b.asset_id is not None and not conn.execute("SELECT 1 FROM media_assets WHERE id=?", (b.asset_id,)).fetchone():
        raise HTTPException(422, "Unknown image asset")
    for v in (b.starts_at, b.ends_at):
        if v:
            try:
                datetime.fromisoformat(v)
            except ValueError:
                raise HTTPException(422, "Dates must be ISO format, e.g. 2026-11-01T09:00")
    if not (b.asset_id or b.title_en.strip() or b.title_ar.strip() or b.body_en.strip() or b.body_ar.strip()):
        raise HTTPException(422, "A slide needs an image or some text")


def _slide_scope(conn, user, game_id):
    """Shared slides (game_id NULL) are for unrestricted accounts only; restricted accounts own their games' slides."""
    ok = allowed_games(conn, user)
    if game_id is None:
        if ok is not None:
            raise HTTPException(403, "Your account can only manage slides for its own games")
    else:
        if not conn.execute("SELECT 1 FROM games WHERE id=?", (game_id,)).fetchone():
            raise HTTPException(422, "Unknown game")
        ensure_game(conn, user, game_id)


def _own_slide(conn, user, sid):
    r = conn.execute("SELECT * FROM brand_slides WHERE id=?", (sid,)).fetchone()
    if not r:
        raise HTTPException(404, "Slide not found")
    _slide_scope(conn, user, r["game_id"])
    return r


@router.get("/slides")
def list_slides(user=Depends(require_viewer), conn=Depends(get_db)):
    ok = allowed_games(conn, user)
    return [slide_dict(conn, r) for r in conn.execute("SELECT * FROM brand_slides ORDER BY sort_order, id")
            if ok is None or r["game_id"] in ok]


@router.post("/slides", status_code=201)
def create_slide(b: SlideIn, user=Depends(require_editor), conn=Depends(get_db)):
    _slide_scope(conn, user, b.game_id)
    _check_slide(conn, b)
    ts = now_iso()
    cur = conn.execute("""INSERT INTO brand_slides(title_en,title_ar,body_en,body_ar,asset_id,bg_color,fit,duration_ms,sort_order,enabled,
                          starts_at,ends_at,created_at,updated_at,game_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (b.title_en, b.title_ar, b.body_en, b.body_ar, b.asset_id, b.bg_color, b.fit, b.duration_ms, b.sort_order,
                        int(b.enabled), b.starts_at or None, b.ends_at or None, ts, ts, b.game_id))
    return slide_dict(conn, conn.execute("SELECT * FROM brand_slides WHERE id=?", (cur.lastrowid,)).fetchone())


@router.put("/slides/{sid}")
def update_slide(sid: int, b: SlideIn, user=Depends(require_editor), conn=Depends(get_db)):
    _own_slide(conn, user, sid)
    _slide_scope(conn, user, b.game_id)
    _check_slide(conn, b)
    conn.execute("""UPDATE brand_slides SET title_en=?,title_ar=?,body_en=?,body_ar=?,asset_id=?,bg_color=?,fit=?,duration_ms=?,
                    sort_order=?,enabled=?,starts_at=?,ends_at=?,updated_at=?,game_id=? WHERE id=?""",
                 (b.title_en, b.title_ar, b.body_en, b.body_ar, b.asset_id, b.bg_color, b.fit, b.duration_ms, b.sort_order,
                  int(b.enabled), b.starts_at or None, b.ends_at or None, now_iso(), b.game_id, sid))
    return slide_dict(conn, conn.execute("SELECT * FROM brand_slides WHERE id=?", (sid,)).fetchone())


@router.delete("/slides/{sid}")
def delete_slide(sid: int, user=Depends(require_editor), conn=Depends(get_db)):
    _own_slide(conn, user, sid)
    conn.execute("DELETE FROM brand_slides WHERE id=?", (sid,))
    return {"ok": True}


# ------------------------------------------------------------------ themes (white-label)
def theme_dict(r):
    return {"id": r["id"], "name": r["name"], "is_active": bool(r["is_active"]), "is_preset": bool(r["is_preset"]),
            "tokens": resolve_theme_tokens(r["tokens"]), "updated_at": r["updated_at"]}


@router.get("/themes")
def list_themes(_=Depends(require_viewer), conn=Depends(get_db)):
    return [theme_dict(r) for r in conn.execute("SELECT * FROM themes ORDER BY is_active DESC, id")]


@router.get("/themes/defaults")
def theme_defaults(_=Depends(require_viewer)):
    return DEFAULT_THEME_TOKENS


@router.get("/themes/{tid}/resolved")
def theme_resolved(tid: int, _=Depends(require_viewer), conn=Depends(get_db)):
    r = conn.execute("SELECT * FROM themes WHERE id=?", (tid,)).fetchone()
    if not r:
        raise HTTPException(404, "Theme not found")
    return themes.resolve_for_game(conn, r)


@router.post("/themes", status_code=201)
def create_theme(b: ThemeIn, _=Depends(require_editor), conn=Depends(get_db)):
    tokens = themes.sanitize_tokens(b.tokens)
    themes.check_assets_exist(conn, tokens)
    ts = now_iso()
    cur = conn.execute("INSERT INTO themes(name,is_active,is_preset,tokens,created_at,updated_at) VALUES(?,0,0,?,?,?)",
                       (b.name, json.dumps(tokens), ts, ts))
    return theme_dict(conn.execute("SELECT * FROM themes WHERE id=?", (cur.lastrowid,)).fetchone())


@router.put("/themes/{tid}")
def update_theme(tid: int, b: ThemeIn, _=Depends(require_editor), conn=Depends(get_db)):
    if not conn.execute("SELECT 1 FROM themes WHERE id=?", (tid,)).fetchone():
        raise HTTPException(404, "Theme not found")
    tokens = themes.sanitize_tokens(b.tokens)
    themes.check_assets_exist(conn, tokens)
    conn.execute("UPDATE themes SET name=?, tokens=?, updated_at=? WHERE id=?", (b.name, json.dumps(tokens), now_iso(), tid))
    return theme_dict(conn.execute("SELECT * FROM themes WHERE id=?", (tid,)).fetchone())


@router.post("/themes/{tid}/activate")
def activate_theme(tid: int, _=Depends(require_editor), conn=Depends(get_db)):
    if not conn.execute("SELECT 1 FROM themes WHERE id=?", (tid,)).fetchone():
        raise HTTPException(404, "Theme not found")
    conn.execute("UPDATE themes SET is_active=CASE WHEN id=? THEN 1 ELSE 0 END", (tid,))
    return {"ok": True}


@router.post("/themes/{tid}/duplicate", status_code=201)
def duplicate_theme(tid: int, _=Depends(require_editor), conn=Depends(get_db)):
    r = conn.execute("SELECT * FROM themes WHERE id=?", (tid,)).fetchone()
    if not r:
        raise HTTPException(404, "Theme not found")
    ts = now_iso()
    cur = conn.execute("INSERT INTO themes(name,is_active,is_preset,tokens,created_at,updated_at) VALUES(?,0,0,?,?,?)",
                       (r["name"] + " (copy)", r["tokens"], ts, ts))
    return theme_dict(conn.execute("SELECT * FROM themes WHERE id=?", (cur.lastrowid,)).fetchone())


@router.delete("/themes/{tid}")
def delete_theme(tid: int, _=Depends(require_editor), conn=Depends(get_db)):
    r = conn.execute("SELECT * FROM themes WHERE id=?", (tid,)).fetchone()
    if not r:
        raise HTTPException(404, "Theme not found")
    if r["is_active"]:
        raise HTTPException(409, "The active theme cannot be deleted. Activate another theme first.")
    conn.execute("DELETE FROM themes WHERE id=?", (tid,))
    return {"ok": True}


@router.get("/themes/{tid}/export")
def export_theme(tid: int, _=Depends(require_viewer), conn=Depends(get_db)):
    """Portable theme: asset ids are replaced by embedded files so a look can be moved to another client's install."""
    r = conn.execute("SELECT * FROM themes WHERE id=?", (tid,)).fetchone()
    if not r:
        raise HTTPException(404, "Theme not found")
    import base64
    tokens = resolve_theme_tokens(r["tokens"])
    embedded = {}
    for key, aid in [*(("assets." + k, v) for k, v in tokens["assets"].items()), ("fonts.font_asset_id", tokens["fonts"]["font_asset_id"])]:
        if aid:
            a = conn.execute("SELECT * FROM media_assets WHERE id=?", (aid,)).fetchone()
            f = config.upload_dir() / a["filename"] if a else None
            if f and f.exists():
                embedded[key] = {"mime": a["mime"], "name": a["original_name"], "data_base64": base64.b64encode(f.read_bytes()).decode()}
    for k in tokens["assets"]:
        tokens["assets"][k] = None
    tokens["fonts"]["font_asset_id"] = None
    return {"format": "fq-theme", "version": 1, "name": r["name"], "tokens": tokens, "embedded_assets": embedded}


@router.post("/themes/import", status_code=201)
def import_theme(payload: dict, _=Depends(require_editor), conn=Depends(get_db)):
    import base64
    if payload.get("format") != "fq-theme":
        raise HTTPException(422, "Not a theme export file")
    tokens = themes.sanitize_tokens(payload.get("tokens") or {})
    for key, emb in (payload.get("embedded_assets") or {}).items():
        try:
            data = base64.b64decode(emb["data_base64"], validate=True)
        except Exception:
            raise HTTPException(422, "Corrupt embedded asset")
        aid = store_asset(conn, data, emb.get("name"))
        if key.startswith("assets.") and key[7:] in tokens["assets"]:
            tokens["assets"][key[7:]] = aid
        elif key == "fonts.font_asset_id":
            tokens["fonts"]["font_asset_id"] = aid
    ts = now_iso()
    name = str(payload.get("name") or "Imported theme")[:80]
    cur = conn.execute("INSERT INTO themes(name,is_active,is_preset,tokens,created_at,updated_at) VALUES(?,0,0,?,?,?)",
                       (name, json.dumps(tokens), ts, ts))
    return theme_dict(conn.execute("SELECT * FROM themes WHERE id=?", (cur.lastrowid,)).fetchone())
