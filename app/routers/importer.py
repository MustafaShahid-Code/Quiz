"""Bulk question import: a spreadsheet (.xlsx or .csv) of questions + the image files, into one game.

Flow used by the admin page:  1) /preview parses the spreadsheet and reports problems row by row (nothing is saved),
2) the browser uploads the referenced images one at a time (each is resized on the server),
3) /commit receives the cleaned rows plus {image filename -> asset id} and creates every question in one transaction."""
import csv
import io
import re
import unicodedata

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import config
from ..db import get_db
from ..questions import create_question, set_status
from ..schemas import OptionIn, QuestionIn
from ..security import ensure_game, require_editor

router = APIRouter(prefix="/api/admin", tags=["import"])

MAX_SHEET_BYTES = 2 * 1024 * 1024
COLUMNS = ["text_en", "text_ar", "option1_en", "option1_ar", "option2_en", "option2_ar", "option3_en", "option3_ar", "option4_en", "option4_ar",
           "correct", "image", "reveal_image", "difficulty", "explanation_en", "explanation_ar"]
EXAMPLES = [
    ["Who is this player?", "من هو هذا اللاعب؟", "Lionel Messi", "ليونيل ميسي", "Cristiano Ronaldo", "كريستيانو رونالدو", "Neymar", "نيمار", "Kylian Mbappé", "كيليان مبابي", 1, "messi_eyes.jpg", "messi_full.jpg", "easy", "", ""],
    ["Who is this player?", "من هو هذا اللاعب؟", "Mohamed Salah", "محمد صلاح", "Sadio Mané", "ساديو ماني", "Son Heung-min", "سون هيونغ مين", "Karim Benzema", "كريم بنزيمة", 1, "salah_eyes.jpg", "salah_full.jpg", "medium", "", ""],
]
LETTERS = {"a": 1, "b": 2, "c": 3, "d": 4}
IMAGE_EXT = re.compile(r"\.(png|jpe?g|webp|gif)$", re.I)


def _norm_header(h) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(h or "").strip().lower()).strip("_")


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = unicodedata.normalize("NFC", str(v)).strip()
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)


def read_sheet(data: bytes, filename: str) -> list[dict]:
    """-> list of {column: text} dicts with normalised header names (empty rows dropped)."""
    if len(data) > MAX_SHEET_BYTES:
        raise HTTPException(413, "The spreadsheet is too large (max 2 MB). It should contain text only: images are uploaded separately.")
    name = (filename or "").lower()
    rows: list[list] = []
    if name.endswith(".xlsx") or data[:2] == b"PK":
        try:
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            ws = wb.worksheets[0]
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
        except Exception:
            raise HTTPException(422, "Could not read this Excel file. Save it as .xlsx (or CSV UTF-8) and try again.")
    elif name.endswith((".csv", ".txt")):
        text = None
        for enc in ("utf-8-sig", "utf-16", "cp1256", "cp1252"):
            try:
                text = data.decode(enc); break
            except UnicodeError:
                continue
        if text is None:
            raise HTTPException(422, "Could not read the CSV file's text encoding. Save it as CSV UTF-8.")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(io.StringIO(text), dialect))
    else:
        raise HTTPException(422, "Upload an .xlsx or .csv file")
    if not rows:
        raise HTTPException(422, "The spreadsheet is empty")
    header = [_norm_header(h) for h in rows[0]]
    if not any(h in header for h in ("text_en", "text_ar", "option1_en", "option1_ar")):
        raise HTTPException(422, "The first row must be the column titles (download the template to see them)")
    out = []
    for i, r in enumerate(rows[1:], start=2):
        d = {header[j]: _cell(r[j]) for j in range(min(len(header), len(r))) if header[j]}
        if any(d.values()):
            d["_row"] = i
            out.append(d)
    if not out:
        raise HTTPException(422, "No question rows found under the column titles")
    if len(out) > config.IMPORT_MAX_ROWS:
        raise HTTPException(422, f"Too many rows ({len(out)}). Import at most {config.IMPORT_MAX_ROWS} questions at a time.")
    return out


def clean_row(d: dict, defaults: dict) -> tuple[dict, list[str]]:
    """Normalise one spreadsheet row -> question fields + a list of problems (empty = fine)."""
    errs: list[str] = []
    opts = []
    for k in range(1, 5):
        en, ar = d.get(f"option{k}_en", ""), d.get(f"option{k}_ar", "")
        if en or ar:
            opts.append({"slot": k, "label_en": en[:200], "label_ar": ar[:200]})
    raw = (d.get("correct", "") or "1").strip().lower()
    correct = LETTERS.get(raw) or (int(raw) if raw.isdigit() else 0)
    if len(opts) < 2:
        errs.append("needs at least 2 answer options")
    slots = [o["slot"] for o in opts]
    if correct not in slots:
        errs.append(f"“correct” must be the number (1-4) of an option that exists, not “{d.get('correct', '')}”")
    diff = (d.get("difficulty", "") or "easy").strip().lower()
    if diff not in ("easy", "medium", "hard"):
        errs.append("difficulty must be easy, medium or hard")
        diff = "easy"
    text_en = d.get("text_en", "") or defaults.get("text_en", "")
    text_ar = d.get("text_ar", "") or defaults.get("text_ar", "")
    langs = [lg for lg, t in (("en", text_en), ("ar", text_ar)) if t and all(o[f"label_{lg}"] for o in opts)]
    if not langs:
        errs.append("needs the question text and every option in English or in Arabic (use the default text boxes if the text is the same for all rows)")
    elif len(opts) >= 2 and (text_en or text_ar):
        for lg, t in (("en", text_en), ("ar", text_ar)):
            labels = [o[f"label_{lg}"] for o in opts]
            if (t or any(labels)) and not (t and all(labels)):
                errs.append(f"{'English' if lg == 'en' else 'Arabic'} is incomplete: fill the question and all options, or leave that language empty")
    for col in ("text_en", "text_ar"):
        if len(d.get(col, "")) > 500:
            errs.append(f"{col} is longer than 500 characters")
    return {"row": d.get("_row"), "text_en": text_en, "text_ar": text_ar, "options": opts, "correct": correct, "difficulty": diff,
            "image": d.get("image", ""), "reveal_image": d.get("reveal_image", ""),
            "explanation_en": d.get("explanation_en", "")[:1000], "explanation_ar": d.get("explanation_ar", "")[:1000],
            "languages": langs}, errs


@router.get("/import/template.csv")
def template_csv(_=Depends(require_editor)):
    from fastapi.responses import Response
    buf = io.StringIO(); w = csv.writer(buf); w.writerow(COLUMNS); w.writerows(EXAMPLES)
    return Response(("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="questions-template.csv"'})


@router.get("/import/template.xlsx")
def template_xlsx(_=Depends(require_editor)):
    from fastapi.responses import Response
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook(); ws = wb.active; ws.title = "Questions"
    ws.append(COLUMNS)
    for r in EXAMPLES:
        ws.append(r)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="2B44FF")
    for i, col in enumerate(ws.columns, start=1):
        ws.column_dimensions[col[0].column_letter].width = 26 if i <= 10 else 18
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=True)
    ws.freeze_panes = "A2"
    help_ws = wb.create_sheet("How to fill")
    for line in [
        "One row = one question.",
        "text_en / text_ar: the question. Leave a language empty if the question is not offered in it. If every row has the same text (e.g. “Who is this player?”) you can leave it empty and type it once on the import page.",
        "option1..option4: the answers (English and/or Arabic). At least 2 options. If a language is used, fill it for the question and for every option.",
        "correct: the number (1-4) of the right option. Put the right answer in any position; the game can shuffle options.",
        "image: file name of the picture shown in the question (e.g. messi_eyes.jpg). reveal_image: file name of the picture shown after a correct answer (e.g. the full player photo).",
        "difficulty: easy, medium or hard (optional). explanation_en / explanation_ar: optional text shown after the answer.",
        "Image files are chosen on the import page: file names must match exactly (capital letters do not matter).",
        "Excel tip: for CSV choose “CSV UTF-8 (Comma delimited)” so Arabic letters are kept.",
    ]:
        help_ws.append([line])
    help_ws.column_dimensions["A"].width = 140
    buf = io.BytesIO(); wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="questions-template.xlsx"'})


@router.post("/games/{gid}/import/preview")
async def preview(gid: int, file: UploadFile = File(...), default_text_en: str = "", default_text_ar: str = "", user=Depends(require_editor), conn=Depends(get_db)):
    if not conn.execute("SELECT 1 FROM games WHERE id=?", (gid,)).fetchone():
        raise HTTPException(404, "Game not found")
    ensure_game(conn, user, gid)
    data = await file.read(MAX_SHEET_BYTES + 1)
    rows = read_sheet(data, file.filename or "")
    defaults = {"text_en": default_text_en.strip(), "text_ar": default_text_ar.strip()}
    items, images = [], {}
    for d in rows:
        row, errs = clean_row(d, defaults)
        for key in ("image", "reveal_image"):
            fn = row[key]
            if fn and not IMAGE_EXT.search(fn):
                errs.append(f"{key} “{fn}” does not look like a picture file name (.jpg, .png, .webp, .gif)")
            elif fn:
                images.setdefault(fn.lower(), fn)
        items.append({**row, "errors": errs})
    return {"rows": items, "images": sorted(images.values(), key=str.lower), "ok": sum(1 for i in items if not i["errors"]), "bad": sum(1 for i in items if i["errors"])}


class CommitRow(BaseModel):
    row: int | None = None
    text_en: str = Field(default="", max_length=500)
    text_ar: str = Field(default="", max_length=500)
    options: list[dict]
    correct: int
    difficulty: str = "easy"
    image: str = Field(default="", max_length=300)
    reveal_image: str = Field(default="", max_length=300)
    explanation_en: str = Field(default="", max_length=1000)
    explanation_ar: str = Field(default="", max_length=1000)


class CommitIn(BaseModel):
    rows: list[CommitRow] = Field(max_length=300)
    assets: dict[str, int] = Field(default_factory=dict)    # lower-case image file name -> asset id (uploaded by the browser)
    publish: bool = False
    default_text_en: str = Field(default="", max_length=500)
    default_text_ar: str = Field(default="", max_length=500)


@router.post("/games/{gid}/import/commit", status_code=201)
def commit(gid: int, body: CommitIn, user=Depends(require_editor), conn=Depends(get_db)):
    g = conn.execute("SELECT * FROM games WHERE id=?", (gid,)).fetchone()
    if not g:
        raise HTTPException(404, "Game not found")
    ensure_game(conn, user, gid)
    if not body.rows:
        raise HTTPException(422, "Nothing to import")
    known = {r[0] for r in conn.execute("SELECT id FROM media_assets")}
    problems, built = [], []
    for r in body.rows:
        # re-validate from scratch: the browser is not trusted
        d = {"_row": r.row, "text_en": r.text_en, "text_ar": r.text_ar, "correct": str(r.correct), "difficulty": r.difficulty,
             "explanation_en": r.explanation_en, "explanation_ar": r.explanation_ar}
        for o in r.options[:4]:
            k = int(o.get("slot", 0) or 0)
            if 1 <= k <= 4:
                d[f"option{k}_en"] = str(o.get("label_en", ""))[:200]; d[f"option{k}_ar"] = str(o.get("label_ar", ""))[:200]
        row, errs = clean_row(d, {"text_en": body.default_text_en.strip(), "text_ar": body.default_text_ar.strip()})
        ids = {}
        for key, fn in (("image", r.image), ("reveal_image", r.reveal_image)):
            if fn:
                aid = body.assets.get(fn.lower())
                if aid is None or aid not in known:
                    errs.append(f"{key} “{fn}” was not uploaded")
                else:
                    ids[key] = aid
        if errs:
            problems.append({"row": r.row, "errors": errs}); continue
        built.append((row, ids))
    if problems:
        raise HTTPException(422, {"message": "Some rows have problems. Nothing was imported.", "errors": [f"Row {p['row']}: {'; '.join(p['errors'])}" for p in problems[:20]]})
    created, published, skipped = [], 0, []
    try:
        order = (conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM questions WHERE game_id=?", (gid,)).fetchone()[0] or 0) + 1
        for i, (row, ids) in enumerate(built):
            q = QuestionIn(text_en=row["text_en"] if "en" in row["languages"] else "", text_ar=row["text_ar"] if "ar" in row["languages"] else "",
                           explanation_en=row["explanation_en"], explanation_ar=row["explanation_ar"], difficulty=row["difficulty"], game_id=gid,
                           image_asset_id=ids.get("image"), reveal_asset_id=ids.get("reveal_image"), sort_order=order + i,
                           options=[OptionIn(label_en=o["label_en"] if "en" in row["languages"] else "", label_ar=o["label_ar"] if "ar" in row["languages"] else "",
                                             is_correct=(o["slot"] == row["correct"])) for o in row["options"]])
            qid = create_question(conn, q)    # each question is created atomically; a failure below removes the ones already created
            created.append(qid)
    except Exception:
        for qid in created:
            conn.execute("DELETE FROM questions WHERE id=?", (qid,))
        raise
    if body.publish:
        for qid, (row, _ids) in zip(created, built):
            try:
                set_status(conn, qid, "published"); published += 1
            except HTTPException as e:
                d = e.detail if isinstance(e.detail, dict) else {}
                skipped.append({"row": row["row"], "issues": d.get("errors") or [str(e.detail)]})
    return {"created": len(created), "published": published, "left_as_draft": skipped, "game": g["slug"]}
