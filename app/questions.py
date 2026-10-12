"""Question domain logic: serialisation, validation, saving."""
import json
import uuid

from fastapi import HTTPException

from .db import now_iso
from .schemas import QuestionIn

LANGS = ("en", "ar")


def media_url(conn, asset_id):
    if not asset_id:
        return None
    r = conn.execute("SELECT filename FROM media_assets WHERE id=?", (asset_id,)).fetchone()
    return f"/media/{r['filename']}" if r else None


def _effective_image_id(q, char):
    return q["image_asset_id"] or (char["asset_id"] if char else None)


def _effective_reveal_id(q, char):
    return q["reveal_asset_id"] or (char["reveal_asset_id"] if char else None)


def get_options(conn, qid):
    return conn.execute("SELECT * FROM answer_options WHERE question_id=? ORDER BY position, id", (qid,)).fetchall()


def languages_available(q, options) -> list[str]:
    """A language is playable when the question text and EVERY option label exist in it."""
    out = []
    for lg in LANGS:
        if (q[f"text_{lg}"] or "").strip() and options and all((o[f"label_{lg}"] or "").strip() for o in options):
            out.append(lg)
    return out


def serialize_question(conn, q, include_correct=True) -> dict:
    options = get_options(conn, q["id"])
    char = conn.execute("SELECT * FROM characters WHERE id=?", (q["character_id"],)).fetchone() if q["character_id"] else None
    cat = conn.execute("SELECT * FROM question_categories WHERE id=?", (q["category_id"],)).fetchone() if q["category_id"] else None
    img_id = _effective_image_id(q, char)
    d = {
        "id": q["id"], "uid": q["uid"], "version": q["version"],
        "text_en": q["text_en"], "text_ar": q["text_ar"],
        "explanation_en": q["explanation_en"], "explanation_ar": q["explanation_ar"],
        "category_id": q["category_id"], "category_en": cat["name_en"] if cat else None, "category_ar": cat["name_ar"] if cat else None,
        "difficulty": q["difficulty"], "status": q["status"], "enabled": bool(q["enabled"]), "sort_order": q["sort_order"],
        "image_asset_id": q["image_asset_id"], "image_url": media_url(conn, img_id),
        "reveal_asset_id": q["reveal_asset_id"], "reveal_url": media_url(conn, _effective_reveal_id(q, char)),
        "character_id": q["character_id"], "character_name_en": char["name_en"] if char else None,
        "character_name_ar": char["name_ar"] if char else None,
        "scheme_id": q["scheme_id"],
        "created_at": q["created_at"], "updated_at": q["updated_at"], "published_at": q["published_at"],
        "languages": languages_available(q, options),
        "option_count": len(options),
        "options": [{"id": o["id"], "position": o["position"], "label_en": o["label_en"], "label_ar": o["label_ar"],
                     **({"is_correct": bool(o["is_correct"])} if include_correct else {})} for o in options],
    }
    if include_correct:
        c = next((o for o in options if o["is_correct"]), None)
        d["correct_option_id"] = c["id"] if c else None
        d["correct_label_en"] = c["label_en"] if c else None
        d["correct_label_ar"] = c["label_ar"] if c else None
    return d


def validate_for_publish(conn, q, require_image=False) -> list[str]:
    errors = []
    options = get_options(conn, q["id"])
    if len(options) < 2:
        errors.append("A published question needs at least two answer options.")
    correct = [o for o in options if o["is_correct"]]
    if len(correct) != 1:
        errors.append(f"Exactly one option must be marked correct (found {len(correct)}).")
    langs = languages_available(q, options)
    if not langs:
        errors.append("Provide the question text and every option label in at least one language (English or Arabic).")
    for lg in LANGS:
        if lg in langs:
            labels = [o[f"label_{lg}"].strip().lower() for o in options]
            if len(set(labels)) != len(labels):
                errors.append(f"Duplicate option labels in {lg.upper()}.")
    char = conn.execute("SELECT * FROM characters WHERE id=?", (q["character_id"],)).fetchone() if q["character_id"] else None
    if require_image:
        iid = _effective_image_id(q, char)
        if not iid:
            errors.append("Add a question image (or choose a character that has one).")
    if q["scheme_id"]:
        sch = conn.execute("SELECT * FROM interaction_schemes WHERE id=?", (q["scheme_id"],)).fetchone()
        if not sch:
            errors.append("The assigned interaction scheme no longer exists.")
        elif not sch["enabled"]:
            errors.append("The assigned interaction scheme is disabled.")
        else:
            errors += scheme_errors(sch, len(options))
    return errors


def scheme_errors(sch, n_options) -> list[str]:
    cfg = json.loads(sch["config"] or "{}")
    errs = []
    if sch["scheme_type"] == "touch_zones":
        for z in cfg.get("zones", []) or []:
            if not (isinstance(z.get("option_index"), int) and 0 <= z["option_index"] < n_options):
                errs.append("Scheme zone refers to an option position that this question does not have.")
                break
    else:
        for m in cfg.get("mappings", []) or []:
            if not (isinstance(m.get("option_index"), int) and 0 <= m["option_index"] < n_options):
                errs.append("Scheme pose mapping refers to an option position that this question does not have.")
                break
    return errs


def _check_refs(conn, p: QuestionIn):
    for table, val, label in (("media_assets", p.image_asset_id, "image"), ("media_assets", p.reveal_asset_id, "reveal image"),
                              ("characters", p.character_id, "character"), ("interaction_schemes", p.scheme_id, "scheme"),
                              ("question_categories", p.category_id, "category")):
        if val is not None and not conn.execute(f"SELECT 1 FROM {table} WHERE id=?", (val,)).fetchone():
            raise HTTPException(422, f"Unknown {label} id {val}")


def create_question(conn, p: QuestionIn) -> int:
    _check_refs(conn, p)
    ts = now_iso()
    conn.execute("BEGIN")
    try:
        cur = conn.execute(
            """INSERT INTO questions(uid,text_en,text_ar,explanation_en,explanation_ar,category_id,difficulty,image_asset_id,
               character_id,reveal_asset_id,scheme_id,status,enabled,sort_order,version,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?, 'draft',?,?,1,?,?)""",
            (str(uuid.uuid4()), p.text_en.strip(), p.text_ar.strip(), p.explanation_en.strip(), p.explanation_ar.strip(),
             p.category_id, p.difficulty, p.image_asset_id, p.character_id, p.reveal_asset_id, p.scheme_id,
             int(p.enabled), p.sort_order, ts, ts))
        qid = cur.lastrowid
        _write_options(conn, qid, p, existing=[])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return qid


def update_question(conn, qid: int, p: QuestionIn):
    q = conn.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
    if not q:
        raise HTTPException(404, "Question not found")
    _check_refs(conn, p)
    conn.execute("BEGIN")
    try:
        conn.execute(
            """UPDATE questions SET text_en=?,text_ar=?,explanation_en=?,explanation_ar=?,category_id=?,difficulty=?,
               image_asset_id=?,character_id=?,reveal_asset_id=?,scheme_id=?,enabled=?,sort_order=?,version=version+1,updated_at=?
               WHERE id=?""",
            (p.text_en.strip(), p.text_ar.strip(), p.explanation_en.strip(), p.explanation_ar.strip(), p.category_id,
             p.difficulty, p.image_asset_id, p.character_id, p.reveal_asset_id, p.scheme_id, int(p.enabled), p.sort_order,
             now_iso(), qid))
        existing = [r["id"] for r in get_options(conn, qid)]
        _write_options(conn, qid, p, existing)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    # a published question that no longer validates must not silently stay live
    q2 = conn.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
    if q2["status"] == "published" and validate_for_publish(conn, q2):
        conn.execute("UPDATE questions SET status='unpublished', updated_at=? WHERE id=?", (now_iso(), qid))
        return True  # auto-unpublished
    return False


def _write_options(conn, qid, p: QuestionIn, existing):
    keep = {o.id for o in p.options if o.id in existing}
    for oid in existing:
        if oid not in keep:
            conn.execute("DELETE FROM answer_options WHERE id=?", (oid,))
    for pos, o in enumerate(p.options):
        if o.id in keep:
            conn.execute("UPDATE answer_options SET position=?,label_en=?,label_ar=?,is_correct=? WHERE id=?",
                         (pos, o.label_en.strip(), o.label_ar.strip(), int(o.is_correct), o.id))
        else:
            conn.execute("INSERT INTO answer_options(question_id,position,label_en,label_ar,is_correct) VALUES(?,?,?,?,?)",
                         (qid, pos, o.label_en.strip(), o.label_ar.strip(), int(o.is_correct)))


def set_status(conn, qid: int, status: str, require_image=False):
    q = conn.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
    if not q:
        raise HTTPException(404, "Question not found")
    if status == "published":
        errs = validate_for_publish(conn, q, require_image)
        if errs:
            raise HTTPException(422, {"message": "Question cannot be published yet", "errors": errs})
        conn.execute("UPDATE questions SET status='published', published_at=?, updated_at=? WHERE id=?",
                     (now_iso(), now_iso(), qid))
    else:
        conn.execute("UPDATE questions SET status=?, updated_at=? WHERE id=?", (status, now_iso(), qid))


def duplicate_question(conn, qid: int) -> int:
    q = conn.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
    if not q:
        raise HTTPException(404, "Question not found")
    opts = get_options(conn, qid)
    ts = now_iso()
    conn.execute("BEGIN")
    try:
        cur = conn.execute(
            """INSERT INTO questions(uid,text_en,text_ar,explanation_en,explanation_ar,category_id,difficulty,image_asset_id,
               character_id,reveal_asset_id,scheme_id,status,enabled,sort_order,version,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,'draft',?,?,1,?,?)""",
            (str(uuid.uuid4()), q["text_en"], q["text_ar"], q["explanation_en"], q["explanation_ar"], q["category_id"],
             q["difficulty"], q["image_asset_id"], q["character_id"], q["reveal_asset_id"], q["scheme_id"], q["enabled"],
             q["sort_order"], ts, ts))
        new_id = cur.lastrowid
        for o in opts:
            conn.execute("INSERT INTO answer_options(question_id,position,label_en,label_ar,is_correct) VALUES(?,?,?,?,?)",
                         (new_id, o["position"], o["label_en"], o["label_ar"], o["is_correct"]))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return new_id
