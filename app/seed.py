"""First-run seeding: admin account, themes, sample categories/questions/schemes and the sponsor slide."""
import json
import os
import secrets
import sys
import uuid
from pathlib import Path

from . import config
from .db import DEFAULT_THEME_TOKENS, THEME_PRESETS, deep_merge, now_iso
from .security import hash_password

SEED_ASSETS = Path(__file__).parent / "seed_assets"

SVGS = {
    "football": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"><circle cx="200" cy="200" r="180" fill="#fff" stroke="#1b1b1b" stroke-width="8"/>
<polygon points="200,120 262,165 238,238 162,238 138,165" fill="#1b1b1b"/>
<g stroke="#1b1b1b" stroke-width="8" stroke-linecap="round"><line x1="200" y1="120" x2="200" y2="40"/><line x1="262" y1="165" x2="330" y2="130"/><line x1="238" y1="238" x2="290" y2="310"/><line x1="162" y1="238" x2="110" y2="310"/><line x1="138" y1="165" x2="70" y2="130"/></g>
<g fill="#1b1b1b"><polygon points="200,40 240,52 232,86 168,86 160,52"/><polygon points="330,130 352,168 322,196 296,170 300,138"/><polygon points="290,310 262,342 224,328 226,290 262,282"/><polygon points="110,310 138,342 176,328 174,290 138,282"/><polygon points="70,130 48,168 78,196 104,170 100,138"/></g></svg>""",
    "trophy": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"><path d="M120 60h160v90c0 55-35 95-80 95s-80-40-80-95z" fill="#f5b800" stroke="#a87800" stroke-width="6"/>
<path d="M120 80H70c0 60 25 90 62 98M280 80h50c0 60-25 90-62 98" fill="none" stroke="#f5b800" stroke-width="16" stroke-linecap="round"/>
<rect x="180" y="245" width="40" height="55" fill="#e0a500"/><rect x="130" y="300" width="140" height="28" rx="6" fill="#a87800"/><rect x="110" y="328" width="180" height="34" rx="8" fill="#6b4a00"/>
<ellipse cx="170" cy="110" rx="14" ry="38" fill="#ffe27a" opacity=".7"/></svg>""",
    "yellow_card": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"><rect x="115" y="50" width="170" height="300" rx="16" fill="#ffd400" stroke="#b39500" stroke-width="6" transform="rotate(-8 200 200)"/></svg>""",
    "whistle": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"><circle cx="150" cy="230" r="90" fill="#2b2b2b"/><circle cx="150" cy="230" r="46" fill="#f4f4f4"/>
<rect x="150" y="140" width="190" height="64" rx="12" fill="#2b2b2b"/><rect x="262" y="120" width="52" height="30" rx="6" fill="#444"/><path d="M60 120c-20-40 10-70 40-60" fill="none" stroke="#d62828" stroke-width="10" stroke-linecap="round"/></svg>""",
    "corner_flag": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"><rect x="190" y="50" width="12" height="310" rx="6" fill="#e9e9e9" stroke="#999" stroke-width="3"/>
<polygon points="202,60 340,110 202,160" fill="#e63946"/><ellipse cx="196" cy="362" rx="60" ry="12" fill="#3a8f3a"/></svg>""",
    "goal": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"><rect x="40" y="90" width="320" height="220" fill="#eef4ff" opacity=".35"/>
<g stroke="#cfd8f7" stroke-width="2">""" + "".join(f'<line x1="{x}" y1="90" x2="{x}" y2="310"/>' for x in range(60, 360, 20)) + "".join(f'<line x1="40" y1="{y}" x2="360" y2="{y}"/>' for y in range(110, 310, 20)) + """</g>
<path d="M40 310V90h320v220" fill="none" stroke="#fff" stroke-width="14" stroke-linejoin="round"/><line x1="10" y1="312" x2="390" y2="312" stroke="#3a8f3a" stroke-width="8"/></svg>""",
}

CATEGORIES = [("equipment", "Equipment", "المعدات"), ("rules", "Rules & Referee", "القوانين والحكم"), ("general", "General", "عام")]

QUESTIONS = [
    ("football", "equipment", "easy", "What is shown in this picture?", "ماذا تظهر هذه الصورة؟",
     "A standard football has a circumference of about 68–70 cm.", "يبلغ محيط كرة القدم القياسية نحو 68–70 سم.",
     [("Basketball", "كرة سلة"), ("Football", "كرة قدم"), ("Tennis Ball", "كرة تنس"), ("Volleyball", "كرة طائرة")], 1),
    ("trophy", "general", "easy", "What is this famous prize called?", "ما اسم هذه الجائزة الشهيرة؟",
     "The winning team lifts the trophy after the final.", "يرفع الفريق الفائز الكأس بعد المباراة النهائية.",
     [("Trophy", "كأس"), ("Medal", "ميدالية"), ("Ribbon", "شريط"), ("Badge", "شارة")], 0),
    ("yellow_card", "rules", "easy", "What does the referee show for a caution?", "ماذا يُظهر الحكم عند توجيه إنذار؟",
     "A second yellow card in the same match becomes a red card.", "الإنذار الثاني في المباراة نفسها يتحول إلى بطاقة حمراء.",
     [("Yellow card", "بطاقة صفراء"), ("Red card", "بطاقة حمراء"), ("Blue card", "بطاقة زرقاء"), ("Green card", "بطاقة خضراء")], 0),
    ("whistle", "rules", "easy", "Who blows this whistle?", "من يستخدم هذه الصافرة؟",
     "The referee controls the match with the whistle.", "يدير الحكم المباراة بالصافرة.",
     [("The goalkeeper", "حارس المرمى"), ("The referee", "الحكم"), ("The coach", "المدرب"), ("A fan", "مشجع")], 1),
    ("corner_flag", "rules", "medium", "What is this marker at the corner of the pitch?", "ما هذه الراية في زاوية الملعب؟",
     "Corner kicks are taken from the corner arc beside this flag.", "تُنفذ الركلات الركنية من قوس الزاوية بجانب هذه الراية.",
     [("Corner flag", "راية الزاوية"), ("Goal post", "القائم"), ("Centre circle", "دائرة المنتصف"), ("Penalty spot", "نقطة الجزاء")], 0),
    ("goal", "equipment", "easy", "What do players try to score in?", "في ماذا يحاول اللاعبون تسجيل الأهداف؟",
     "A goal is 7.32 m wide and 2.44 m high.", "عرض المرمى 7.32 متر وارتفاعه 2.44 متر.",
     [("The goal", "المرمى"), ("A basket", "السلة"), ("A wicket", "الويكيت"), ("A hole", "الحفرة")], 0),
]


def _insert_asset(conn, filename_base, data: bytes, mime, ext, original, w=None, h=None) -> int:
    fname = f"{uuid.uuid4().hex}.{ext}"
    (config.upload_dir() / fname).write_bytes(data)
    cur = conn.execute("INSERT INTO media_assets(filename,original_name,mime,size_bytes,width,height,created_at) VALUES(?,?,?,?,?,?,?)",
                       (fname, original, mime, len(data), w, h, now_iso()))
    return cur.lastrowid


def ensure_admin(conn):
    if conn.execute("SELECT 1 FROM admin_users LIMIT 1").fetchone():
        return
    user = os.environ.get("FQ_ADMIN_USER", "admin")
    pw = os.environ.get("FQ_ADMIN_PASSWORD")
    generated = pw is None
    if generated:
        pw = secrets.token_urlsafe(12) + "aA1"
    conn.execute("INSERT INTO admin_users(username,password_hash,role,must_change_password,created_at) VALUES(?,?,'admin',?,?)",
                 (user, hash_password(pw), int(generated), now_iso()))
    if generated:
        print("\n" + "=" * 62 + f"\n  First-run administrator account created\n  username: {user}\n  password: {pw}\n  (shown once - you will be asked to change it)\n" + "=" * 62 + "\n", file=sys.stderr)


def seed_content(conn):
    if conn.execute("SELECT 1 FROM settings WHERE key='_seeded'").fetchone():
        return
    ts = now_iso()
    # themes
    first = True
    for name, over in THEME_PRESETS.items():
        tokens = deep_merge(DEFAULT_THEME_TOKENS, over)
        conn.execute("INSERT INTO themes(name,is_active,is_preset,tokens,created_at,updated_at) VALUES(?,?,1,?,?,?)",
                     (name, int(first), json.dumps(tokens), ts, ts))
        first = False
    # categories
    cat_ids = {}
    for slug, en, ar in CATEGORIES:
        cat_ids[slug] = conn.execute("INSERT INTO question_categories(slug,name_en,name_ar) VALUES(?,?,?)", (slug, en, ar)).lastrowid
    # schemes
    conn.execute("INSERT INTO interaction_schemes(name,description,scheme_type,config,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                 ("Standard 2×2 grid", "Four large answer buttons in a 2×2 grid (default layout).", "touch_zones",
                  json.dumps({"layout": "grid2x2"}), 1, ts, ts))
    conn.execute("INSERT INTO interaction_schemes(name,description,scheme_type,config,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                 ("Pose answers (needs camera)", "Players answer with a body pose. Requires an external pose-estimation service posting to /api/input/pose; the RPLIDAR cannot recognise poses.",
                  "pose_mapping", json.dumps({"mappings": [{"pose": "arm_up_left", "option_index": 0}, {"pose": "arm_up_right", "option_index": 1},
                                                           {"pose": "both_arms_up", "option_index": 2}, {"pose": "arms_crossed", "option_index": 3}],
                                              "min_confidence": 0.75, "hold_ms": 800}), 0, ts, ts))
    # sample questions
    asset_ids = {}
    for key, svg in SVGS.items():
        asset_ids[key] = _insert_asset(conn, key, svg.encode(), "image/svg+xml", "svg", f"sample-{key}.svg")
    for pos, (img, cat, diff, ten, tar, exen, exar, opts, correct) in enumerate(QUESTIONS):
        qid = conn.execute(
            """INSERT INTO questions(uid,text_en,text_ar,explanation_en,explanation_ar,category_id,difficulty,image_asset_id,status,
               enabled,sort_order,version,created_at,updated_at,published_at,game_id)
               VALUES(?,?,?,?,?,?,?,?,'published',1,?,1,?,?,?,(SELECT id FROM games WHERE is_default=1))""",
            (str(uuid.uuid4()), ten, tar, exen, exar, cat_ids[cat], diff, asset_ids[img], pos, ts, ts, ts)).lastrowid
        for i, (en, ar) in enumerate(opts):
            conn.execute("INSERT INTO answer_options(question_id,position,label_en,label_ar,is_correct) VALUES(?,?,?,?,?)",
                         (qid, i, en, ar, int(i == correct)))
    # branding slides
    sponsor = SEED_ASSETS / "sponsors-riyad-bank-alhilal.png"
    if sponsor.exists():
        from PIL import Image
        w, h = Image.open(sponsor).size
        aid = _insert_asset(conn, "sponsors", sponsor.read_bytes(), "image/png", "png", sponsor.name, w, h)
        conn.execute("""INSERT INTO brand_slides(title_en,title_ar,asset_id,bg_color,fit,duration_ms,sort_order,enabled,created_at,updated_at)
                        VALUES('Sponsors','الرعاة',?, '#000000','contain',7000,0,1,?,?)""", (aid, ts, ts))
    conn.execute("""INSERT INTO brand_slides(title_en,title_ar,body_en,body_ar,bg_color,fit,duration_ms,sort_order,enabled,created_at,updated_at)
                    VALUES('Football Challenge!','تحدي كرة القدم!','Test your football knowledge','اختبر معلوماتك الكروية','#0b0b52','contain',6000,1,1,?,?)""", (ts, ts))
    conn.execute("INSERT INTO settings(key,value) VALUES('_seeded','true')")


def run_all(conn):
    ensure_admin(conn)
    if os.environ.get("FQ_SEED", "1") != "0":
        seed_content(conn)
