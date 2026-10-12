"""Questions, categories, characters and interaction schemes (admin)."""
import json

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import questions as qs
from ..db import get_db, load_settings, now_iso
from ..schemas import CategoryIn, CharacterIn, QuestionIn, SchemeIn, StatusIn
from ..security import require_editor, require_viewer

router = APIRouter(prefix="/api/admin", tags=["content"])

SORTS = {"id": "q.id", "text": "q.text_en", "difficulty": "q.difficulty", "status": "q.status",
         "updated_at": "q.updated_at", "category": "c.name_en"}


# ------------------------------------------------------------------ questions
@router.get("/questions")
def list_questions(q: str = "", status: str = "", category_id: int | None = None, difficulty: str = "",
                   sort: str = "updated_at", order: str = "desc", page: int = Query(1, ge=1),
                   page_size: int = Query(20, ge=1, le=100), _=Depends(require_viewer), conn=Depends(get_db)):
    where, args = [], []
    if q.strip():
        if q.strip().isdigit():
            where.append("(q.id=? OR q.text_en LIKE ? OR q.text_ar LIKE ?)")
            args += [int(q), f"%{q.strip()}%", f"%{q.strip()}%"]
        else:
            where.append("(q.text_en LIKE ? OR q.text_ar LIKE ? OR EXISTS(SELECT 1 FROM answer_options o WHERE o.question_id=q.id AND (o.label_en LIKE ? OR o.label_ar LIKE ?)))")
            args += [f"%{q.strip()}%"] * 4
    if status in ("draft", "published", "unpublished"):
        where.append("q.status=?"); args.append(status)
    if category_id:
        where.append("q.category_id=?"); args.append(category_id)
    if difficulty in ("easy", "medium", "hard"):
        where.append("q.difficulty=?"); args.append(difficulty)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    col = SORTS.get(sort, "q.updated_at")
    direction = "ASC" if order.lower() == "asc" else "DESC"
    base = f"FROM questions q LEFT JOIN question_categories c ON c.id=q.category_id {w}"
    total = conn.execute(f"SELECT COUNT(*) {base}", args).fetchone()[0]
    rows = conn.execute(f"SELECT q.* {base} ORDER BY {col} {direction}, q.id DESC LIMIT ? OFFSET ?",
                        args + [page_size, (page - 1) * page_size]).fetchall()
    return {"total": total, "page": page, "page_size": page_size, "items": [qs.serialize_question(conn, r) for r in rows]}


def _get_q(conn, qid):
    row = conn.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
    if not row:
        raise HTTPException(404, "Question not found")
    return row


@router.get("/questions/{qid}")
def get_question(qid: int, _=Depends(require_viewer), conn=Depends(get_db)):
    return qs.serialize_question(conn, _get_q(conn, qid))


@router.get("/questions/{qid}/validate")
def validate_question(qid: int, _=Depends(require_viewer), conn=Depends(get_db)):
    errs = qs.validate_for_publish(conn, _get_q(conn, qid))
    return {"ok": not errs, "errors": errs}


@router.get("/questions/{qid}/preview")
def preview_question(qid: int, lang: str = "en", _=Depends(require_viewer), conn=Depends(get_db)):
    """Full payload including the correct answer, for the admin preview only."""
    from ..quiz import _snapshot_question
    if lang not in qs.LANGS:
        raise HTTPException(422, "Unsupported language")
    snap = _snapshot_question(conn, _get_q(conn, qid), lang, False)
    return {"question": snap, "lang": lang, "settings": load_settings(conn)}


@router.post("/questions", status_code=201)
def create_question(body: QuestionIn, _=Depends(require_editor), conn=Depends(get_db)):
    qid = qs.create_question(conn, body)
    return qs.serialize_question(conn, _get_q(conn, qid))


@router.put("/questions/{qid}")
def update_question(qid: int, body: QuestionIn, _=Depends(require_editor), conn=Depends(get_db)):
    auto = qs.update_question(conn, qid, body)
    return {"question": qs.serialize_question(conn, _get_q(conn, qid)), "auto_unpublished": auto}


@router.post("/questions/{qid}/duplicate", status_code=201)
def duplicate(qid: int, _=Depends(require_editor), conn=Depends(get_db)):
    return qs.serialize_question(conn, _get_q(conn, qs.duplicate_question(conn, qid)))


@router.post("/questions/{qid}/status")
def set_status(qid: int, body: StatusIn, _=Depends(require_editor), conn=Depends(get_db)):
    qs.set_status(conn, qid, body.status)
    return qs.serialize_question(conn, _get_q(conn, qid))


@router.delete("/questions/{qid}")
def delete_question(qid: int, _=Depends(require_editor), conn=Depends(get_db)):
    _get_q(conn, qid)
    conn.execute("DELETE FROM questions WHERE id=?", (qid,))  # past responses keep question_uid/text
    return {"ok": True}


# ------------------------------------------------------------------ categories
@router.get("/categories")
def list_categories(_=Depends(require_viewer), conn=Depends(get_db)):
    return [dict(r) for r in conn.execute(
        "SELECT c.*, (SELECT COUNT(*) FROM questions q WHERE q.category_id=c.id) AS question_count FROM question_categories c ORDER BY name_en")]


@router.post("/categories", status_code=201)
def create_category(body: CategoryIn, _=Depends(require_editor), conn=Depends(get_db)):
    if conn.execute("SELECT 1 FROM question_categories WHERE slug=?", (body.slug,)).fetchone():
        raise HTTPException(409, "Slug already exists")
    cur = conn.execute("INSERT INTO question_categories(slug,name_en,name_ar) VALUES(?,?,?)", (body.slug, body.name_en, body.name_ar))
    return {"id": cur.lastrowid}


@router.put("/categories/{cid}")
def update_category(cid: int, body: CategoryIn, _=Depends(require_editor), conn=Depends(get_db)):
    if not conn.execute("SELECT 1 FROM question_categories WHERE id=?", (cid,)).fetchone():
        raise HTTPException(404, "Category not found")
    if conn.execute("SELECT 1 FROM question_categories WHERE slug=? AND id<>?", (body.slug, cid)).fetchone():
        raise HTTPException(409, "Slug already exists")
    conn.execute("UPDATE question_categories SET slug=?,name_en=?,name_ar=? WHERE id=?", (body.slug, body.name_en, body.name_ar, cid))
    return {"ok": True}


@router.delete("/categories/{cid}")
def delete_category(cid: int, _=Depends(require_editor), conn=Depends(get_db)):
    conn.execute("DELETE FROM question_categories WHERE id=?", (cid,))
    return {"ok": True}


# ------------------------------------------------------------------ characters
def _char(conn, r):
    d = dict(r)
    d["metadata"] = json.loads(d["metadata"] or "{}")
    d["image_url"] = qs.media_url(conn, r["asset_id"])
    d["reveal_url"] = qs.media_url(conn, r["reveal_asset_id"])
    d["usage_count"] = conn.execute("SELECT COUNT(*) FROM questions WHERE character_id=?", (r["id"],)).fetchone()[0]
    return d


def _check_assets(conn, *ids):
    for i in ids:
        if i is not None and not conn.execute("SELECT 1 FROM media_assets WHERE id=?", (i,)).fetchone():
            raise HTTPException(422, f"Unknown asset id {i}")


@router.get("/characters")
def list_characters(q: str = "", category: str = "", _=Depends(require_viewer), conn=Depends(get_db)):
    where, args = [], []
    if q.strip():
        where.append("(name_en LIKE ? OR name_ar LIKE ?)"); args += [f"%{q.strip()}%"] * 2
    if category:
        where.append("category=?"); args.append(category)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    return [_char(conn, r) for r in conn.execute(f"SELECT * FROM characters {w} ORDER BY name_en, id", args)]


@router.post("/characters", status_code=201)
def create_character(body: CharacterIn, _=Depends(require_editor), conn=Depends(get_db)):
    if not (body.name_en.strip() or body.name_ar.strip()):
        raise HTTPException(422, "Enter a name in English or Arabic")
    _check_assets(conn, body.asset_id, body.reveal_asset_id)
    ts = now_iso()
    cur = conn.execute("""INSERT INTO characters(name_en,name_ar,description_en,description_ar,category,metadata,asset_id,reveal_asset_id,created_at,updated_at)
                          VALUES(?,?,?,?,?,?,?,?,?,?)""",
                       (body.name_en.strip(), body.name_ar.strip(), body.description_en, body.description_ar, body.category,
                        json.dumps(body.metadata, ensure_ascii=False), body.asset_id, body.reveal_asset_id, ts, ts))
    return _char(conn, conn.execute("SELECT * FROM characters WHERE id=?", (cur.lastrowid,)).fetchone())


@router.put("/characters/{cid}")
def update_character(cid: int, body: CharacterIn, _=Depends(require_editor), conn=Depends(get_db)):
    if not conn.execute("SELECT 1 FROM characters WHERE id=?", (cid,)).fetchone():
        raise HTTPException(404, "Character not found")
    _check_assets(conn, body.asset_id, body.reveal_asset_id)
    conn.execute("""UPDATE characters SET name_en=?,name_ar=?,description_en=?,description_ar=?,category=?,metadata=?,asset_id=?,
                    reveal_asset_id=?,updated_at=? WHERE id=?""",
                 (body.name_en.strip(), body.name_ar.strip(), body.description_en, body.description_ar, body.category,
                  json.dumps(body.metadata, ensure_ascii=False), body.asset_id, body.reveal_asset_id, now_iso(), cid))
    return _char(conn, conn.execute("SELECT * FROM characters WHERE id=?", (cid,)).fetchone())


@router.delete("/characters/{cid}")
def delete_character(cid: int, _=Depends(require_editor), conn=Depends(get_db)):
    n = conn.execute("SELECT COUNT(*) FROM questions WHERE character_id=?", (cid,)).fetchone()[0]
    if n:
        raise HTTPException(409, f"This character is used by {n} question(s). Remove it from them first.")
    conn.execute("DELETE FROM characters WHERE id=?", (cid,))
    return {"ok": True}


# ------------------------------------------------------------------ interaction schemes
def validate_scheme_config(scheme_type: str, cfg: dict):
    if scheme_type == "touch_zones":
        layout = cfg.get("layout", "grid2x2")
        if layout not in ("grid2x2", "row", "column", "custom"):
            raise HTTPException(422, "layout must be grid2x2, row, column or custom")
        zones = cfg.get("zones", [])
        if layout == "custom" and not zones:
            raise HTTPException(422, "A custom layout needs at least one zone")
        for z in zones:
            for k in ("x", "y", "w", "h"):
                if not isinstance(z.get(k), (int, float)) or not 0 <= z[k] <= 1:
                    raise HTTPException(422, f"zone.{k} must be a number between 0 and 1 (fraction of the screen)")
            if not isinstance(z.get("option_index"), int) or z["option_index"] < 0:
                raise HTTPException(422, "zone.option_index must be a non-negative integer")
    else:
        maps = cfg.get("mappings", [])
        if not maps:
            raise HTTPException(422, "Add at least one pose mapping")
        seen = set()
        for m in maps:
            pose = str(m.get("pose", "")).strip()
            if not pose or len(pose) > 60 or not isinstance(m.get("option_index"), int) or m["option_index"] < 0:
                raise HTTPException(422, "Each mapping needs a pose label and a non-negative option_index")
            if pose in seen:
                raise HTTPException(422, f"Pose {pose!r} is mapped twice")
            seen.add(pose)
        mc = cfg.get("min_confidence", 0.7)
        if not isinstance(mc, (int, float)) or not 0 <= mc <= 1:
            raise HTTPException(422, "min_confidence must be between 0 and 1")


def _scheme(conn, r):
    d = dict(r)
    d["config"] = json.loads(d["config"] or "{}")
    d["enabled"] = bool(d["enabled"])
    d["usage_count"] = conn.execute("SELECT COUNT(*) FROM questions WHERE scheme_id=?", (r["id"],)).fetchone()[0]
    d["requires_external_provider"] = d["scheme_type"] == "pose_mapping"
    return d


@router.get("/schemes")
def list_schemes(_=Depends(require_viewer), conn=Depends(get_db)):
    return [_scheme(conn, r) for r in conn.execute("SELECT * FROM interaction_schemes ORDER BY id")]


@router.get("/schemes/{sid}")
def get_scheme(sid: int, _=Depends(require_viewer), conn=Depends(get_db)):
    r = conn.execute("SELECT * FROM interaction_schemes WHERE id=?", (sid,)).fetchone()
    if not r:
        raise HTTPException(404, "Scheme not found")
    return _scheme(conn, r)


@router.post("/schemes", status_code=201)
def create_scheme(body: SchemeIn, _=Depends(require_editor), conn=Depends(get_db)):
    validate_scheme_config(body.scheme_type, body.config)
    ts = now_iso()
    cur = conn.execute("INSERT INTO interaction_schemes(name,description,scheme_type,config,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                       (body.name, body.description, body.scheme_type, json.dumps(body.config), int(body.enabled), ts, ts))
    return _scheme(conn, conn.execute("SELECT * FROM interaction_schemes WHERE id=?", (cur.lastrowid,)).fetchone())


@router.put("/schemes/{sid}")
def update_scheme(sid: int, body: SchemeIn, _=Depends(require_editor), conn=Depends(get_db)):
    if not conn.execute("SELECT 1 FROM interaction_schemes WHERE id=?", (sid,)).fetchone():
        raise HTTPException(404, "Scheme not found")
    validate_scheme_config(body.scheme_type, body.config)
    conn.execute("UPDATE interaction_schemes SET name=?,description=?,scheme_type=?,config=?,enabled=?,updated_at=? WHERE id=?",
                 (body.name, body.description, body.scheme_type, json.dumps(body.config), int(body.enabled), now_iso(), sid))
    # disabling a scheme that published questions rely on takes those questions offline (they no longer validate)
    for r in conn.execute("SELECT * FROM questions WHERE scheme_id=? AND status='published'", (sid,)).fetchall():
        if qs.validate_for_publish(conn, r):
            conn.execute("UPDATE questions SET status='unpublished', updated_at=? WHERE id=?", (now_iso(), r["id"]))
    return _scheme(conn, conn.execute("SELECT * FROM interaction_schemes WHERE id=?", (sid,)).fetchone())


@router.post("/schemes/{sid}/duplicate", status_code=201)
def duplicate_scheme(sid: int, _=Depends(require_editor), conn=Depends(get_db)):
    r = conn.execute("SELECT * FROM interaction_schemes WHERE id=?", (sid,)).fetchone()
    if not r:
        raise HTTPException(404, "Scheme not found")
    ts = now_iso()
    cur = conn.execute("INSERT INTO interaction_schemes(name,description,scheme_type,config,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                       (r["name"] + " (copy)", r["description"], r["scheme_type"], r["config"], 0, ts, ts))
    return _scheme(conn, conn.execute("SELECT * FROM interaction_schemes WHERE id=?", (cur.lastrowid,)).fetchone())


@router.delete("/schemes/{sid}")
def delete_scheme(sid: int, force: bool = False, _=Depends(require_editor), conn=Depends(get_db)):
    n = conn.execute("SELECT COUNT(*) FROM questions WHERE scheme_id=?", (sid,)).fetchone()[0]
    if n and not force:
        raise HTTPException(409, f"This scheme is assigned to {n} question(s). Unassign them first, or delete with force to unassign automatically.")
    conn.execute("DELETE FROM interaction_schemes WHERE id=?", (sid,))
    return {"ok": True}


@router.get("/schemes/{sid}/preview")
def preview_scheme(sid: int, lang: str = "en", _=Depends(require_viewer), conn=Depends(get_db)):
    r = conn.execute("SELECT * FROM interaction_schemes WHERE id=?", (sid,)).fetchone()
    if not r:
        raise HTTPException(404, "Scheme not found")
    n = 4
    sample = {
        "question_id": 0, "uid": "preview", "version": 0, "difficulty": "easy", "category": None, "character_name": None,
        "text": "What is shown in this picture?" if lang == "en" else "ماذا تظهر هذه الصورة؟",
        "explanation": "", "image_url": None, "reveal_url": None,
        "scheme": {"type": r["scheme_type"], "config": json.loads(r["config"] or "{}")},
        "options": [{"id": i + 1, "label": (["Basketball", "Football", "Tennis Ball", "Volleyball"] if lang == "en"
                                            else ["كرة سلة", "كرة قدم", "كرة تنس", "كرة طائرة"])[i], "is_correct": i == 1} for i in range(n)],
    }
    return {"question": sample, "lang": lang, "settings": load_settings(conn)}
