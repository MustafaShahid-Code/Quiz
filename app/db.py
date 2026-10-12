"""SQLite access, versioned migrations and default settings."""
import json
import sqlite3
from datetime import datetime, timezone

from . import config


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.db_path(), timeout=15, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def get_db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


MIGRATIONS_UNSORTED = [
    (1, "initial schema", """
CREATE TABLE admin_users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin','editor','viewer')),
  is_active INTEGER NOT NULL DEFAULT 1,
  must_change_password INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  last_login_at TEXT
);
CREATE TABLE login_attempts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL, ip TEXT, success INTEGER NOT NULL, at REAL NOT NULL
);
CREATE INDEX idx_login_attempts ON login_attempts(username, at);
CREATE TABLE media_assets(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  filename TEXT UNIQUE NOT NULL,
  original_name TEXT, mime TEXT NOT NULL, size_bytes INTEGER NOT NULL,
  width INTEGER, height INTEGER, created_at TEXT NOT NULL
);
CREATE TABLE characters(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name_en TEXT NOT NULL DEFAULT '', name_ar TEXT NOT NULL DEFAULT '',
  description_en TEXT NOT NULL DEFAULT '', description_ar TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT 'player',
  metadata TEXT NOT NULL DEFAULT '{}',
  asset_id INTEGER REFERENCES media_assets(id),
  reveal_asset_id INTEGER REFERENCES media_assets(id),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE question_categories(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT UNIQUE NOT NULL, name_en TEXT NOT NULL, name_ar TEXT NOT NULL DEFAULT ''
);
CREATE TABLE interaction_schemes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
  scheme_type TEXT NOT NULL CHECK(scheme_type IN ('touch_zones','pose_mapping')),
  config TEXT NOT NULL DEFAULT '{}',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE questions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  uid TEXT UNIQUE NOT NULL,
  text_en TEXT NOT NULL DEFAULT '', text_ar TEXT NOT NULL DEFAULT '',
  explanation_en TEXT NOT NULL DEFAULT '', explanation_ar TEXT NOT NULL DEFAULT '',
  category_id INTEGER REFERENCES question_categories(id) ON DELETE SET NULL,
  difficulty TEXT NOT NULL DEFAULT 'easy' CHECK(difficulty IN ('easy','medium','hard')),
  image_asset_id INTEGER REFERENCES media_assets(id),
  character_id INTEGER REFERENCES characters(id),
  reveal_asset_id INTEGER REFERENCES media_assets(id),
  scheme_id INTEGER REFERENCES interaction_schemes(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published','unpublished')),
  enabled INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 0,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, published_at TEXT
);
CREATE TABLE answer_options(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  position INTEGER NOT NULL DEFAULT 0,
  label_en TEXT NOT NULL DEFAULT '', label_ar TEXT NOT NULL DEFAULT '',
  is_correct INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_options_question ON answer_options(question_id);
CREATE TABLE game_sessions(
  id TEXT PRIMARY KEY,
  lang TEXT NOT NULL,
  started_at TEXT NOT NULL, finished_at TEXT,
  score INTEGER NOT NULL DEFAULT 0, correct_count INTEGER NOT NULL DEFAULT 0,
  total_questions INTEGER NOT NULL DEFAULT 0,
  current_index INTEGER NOT NULL DEFAULT 0,
  snapshot TEXT NOT NULL,
  settings_snapshot TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE game_responses(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL REFERENCES game_sessions(id) ON DELETE CASCADE,
  question_id INTEGER, question_uid TEXT, question_version INTEGER, question_text TEXT,
  option_id INTEGER, option_label TEXT,
  is_correct INTEGER NOT NULL, attempt_no INTEGER NOT NULL DEFAULT 1,
  points INTEGER NOT NULL DEFAULT 0,
  input_source TEXT NOT NULL DEFAULT 'mouse',
  response_ms INTEGER, answered_at TEXT NOT NULL
);
CREATE INDEX idx_responses_session ON game_responses(session_id);
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sensor_configs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0,
  sensor_model TEXT NOT NULL DEFAULT 'S2',
  source_type TEXT NOT NULL DEFAULT 'none',
  params TEXT NOT NULL DEFAULT '{}',
  thresholds TEXT NOT NULL DEFAULT '{}',
  calibration TEXT NOT NULL DEFAULT '{}',
  validation TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""),
    (3, "themes (white-label)", """
CREATE TABLE themes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 0,
  is_preset INTEGER NOT NULL DEFAULT 0,
  tokens TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""),
    (2, "branding slides", """
CREATE TABLE brand_slides(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title_en TEXT NOT NULL DEFAULT '', title_ar TEXT NOT NULL DEFAULT '',
  body_en TEXT NOT NULL DEFAULT '', body_ar TEXT NOT NULL DEFAULT '',
  asset_id INTEGER REFERENCES media_assets(id),
  bg_color TEXT NOT NULL DEFAULT '#000000',
  fit TEXT NOT NULL DEFAULT 'contain' CHECK(fit IN ('contain','cover')),
  duration_ms INTEGER NOT NULL DEFAULT 6000,
  sort_order INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1,
  starts_at TEXT, ends_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""),
]


MIGRATIONS = sorted(MIGRATIONS_UNSORTED, key=lambda m: m[0])


def migrate(conn: sqlite3.Connection | None = None) -> list[int]:
    own = conn is None
    conn = conn or connect()
    applied = []
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)")
        done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        for version, name, sql in MIGRATIONS:
            if version in done:
                continue
            conn.execute("BEGIN")
            try:
                for stmt in [s.strip() for s in sql.split(";\n") if s.strip()]:
                    conn.execute(stmt)
                conn.execute("INSERT INTO schema_migrations VALUES (?,?,?)", (version, name, now_iso()))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            applied.append(version)
    finally:
        if own:
            conn.close()
    return applied


DEFAULT_SETTINGS = {
    # branding
    "title_en": "Football Challenge!", "title_ar": "تحدي كرة القدم!",
    "tagline_en": "Do you know the star?", "tagline_ar": "هل عرفت النجم؟",
    "instructions_en": "Touch the correct answer on the screen.",
    "instructions_ar": "المس الإجابة الصحيحة على الشاشة.",
    # platform white-labelling (the admin panel itself) - visual game theme lives in the `themes` table
    "client_name": "", "admin_product_name": "Football Quiz Platform",
    "admin_logo_asset_id": None, "favicon_asset_id": None, "admin_primary_color": "#2b44ff",
    "login_layout": "split", "login_bg_asset_id": None, "login_color_2": "#0b1238",
    "login_headline": "Welcome back", "login_subtext": "Sign in to manage the game",
    "login_features": ["Questions in English and Arabic", "Re-skin the game in one click", "Track every session"],
    "login_footer": "",
    # branding / attract screen
    "branding_enabled": True,
    "branding_default_duration_ms": 6000,
    "branding_hint_en": "Touch the screen to play", "branding_hint_ar": "المس الشاشة لتبدأ اللعب",
    # language
    "default_language": "en", "enabled_languages": ["en", "ar"],
    # session rules
    "questions_per_session": 5, "randomize_questions": True, "randomize_options": False,
    "retries_per_question": 0, "retry_points_fraction": 0.5,
    # scoring
    "points_correct": 10, "points_incorrect": 0, "difficulty_bonus": {"easy": 1.0, "medium": 1.5, "hard": 2.0},
    "high_score_percent": 70,
    # answer confirmation: the chosen option is highlighted and the player gets a few seconds to
    # change their mind before the answer is submitted and judged
    "answer_timer_enabled": True, "answer_time_limit_ms": 5000,
    "timeout_message_en": "Time's up!", "timeout_message_ar": "انتهى الوقت!",
    "confirm_enabled": True, "confirm_delay_ms": 3000, "confirm_retouch_locks": True,
    "confirm_text_en": "Are you sure?", "confirm_text_ar": "متأكد؟",
    # presentation
    "auto_advance": True, "auto_advance_delay_ms": 4500, "show_explanations": True,
    "sound_enabled": True, "idle_reset_seconds": 60, "show_touch_cursor": True,
    "correct_title_en": "CORRECT ANSWER!", "correct_title_ar": "إجابة صحيحة!",
    "correct_messages_en": ["GOOOAL! ⚽ Great answer! 🎯", "What a finish! ⚽"],
    "correct_messages_ar": ["جوووووول! ⚽ يا سلام! إجابة بالملي 🎯", "ضربة معلم! ⚽"],
    "incorrect_messages_en": ["Good try! Let's try the next one."],
    "incorrect_messages_ar": ["محاولة جيدة! لننتقل للسؤال التالي."],
    "retry_message_en": "Not quite — try again!", "retry_message_ar": "ليست الصحيحة — حاول مرة أخرى!",
}

PUBLIC_SETTING_KEYS = [k for k in DEFAULT_SETTINGS]  # nothing in settings is secret


def load_settings(conn) -> dict:
    s = dict(DEFAULT_SETTINGS)
    for r in conn.execute("SELECT key, value FROM settings"):
        if r["key"] in s:
            try:
                s[r["key"]] = json.loads(r["value"])
            except ValueError:
                pass
    return s


def save_settings(conn, values: dict):
    for k, v in values.items():
        if k in DEFAULT_SETTINGS:
            conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (k, json.dumps(v, ensure_ascii=False)))


# ---------------------------------------------------------------------------------------------
# Themes (white-label). Tokens are deep-merged over these defaults so missing keys never break the game.
DEFAULT_THEME_TOKENS = {
    "colors": {
        "bg_from": "#0b0b52", "bg_to": "#04042e", "bg_glow": "#1c46b8",
        "text": "#ffffff", "text_muted": "#b9c3ff", "title": "#ffffff", "accent_line": "#1aa59a",
        "button_bg": "#0a1cff", "button_text": "#ffffff", "button_hover": "#2a3bff",
        "button_selected_border": "#ffffff",
        "card_bg": "#ffffff",
        "correct": "#19c37d", "incorrect": "#ff3b5c",
        "burst_bg": "#ffd814", "burst_text": "#2a0a6b", "burst_stroke": "#000000",
        "branding_bg": "#000000",
        "confetti_1": "#ffd814", "confetti_2": "#ff3b6b", "confetti_3": "#9c1fa5", "confetti_4": "#1a0f8f",
    },
    "fonts": {
        "family_en": "'Poppins','Segoe UI',Arial,sans-serif",
        "family_ar": "'Cairo','Tajawal','Noto Sans Arabic','Segoe UI',Tahoma,sans-serif",
        "font_asset_id": None,
    },
    "shape": {"button_radius": 16, "card_radius": 22, "button_style": "solid"},   # solid | outline | glass
    "assets": {"logo_left_asset_id": None, "logo_right_asset_id": None, "background_asset_id": None},
    "effects": {"background_overlay": 0.0, "swoosh": True, "confetti": True, "stadium_lights": True},
}

THEME_PRESETS = {
    "Midnight Blue": {},
    "Emerald Pitch": {"colors": {"bg_from": "#06301f", "bg_to": "#021510", "bg_glow": "#1fa65a", "accent_line": "#ffd814",
                                 "button_bg": "#0f8a4b", "button_hover": "#13a85d", "text_muted": "#bfe9d2",
                                 "burst_bg": "#ffffff", "burst_text": "#06301f",
                                 "confetti_1": "#ffd814", "confetti_2": "#ffffff", "confetti_3": "#19c37d", "confetti_4": "#0f8a4b"}},
    "Royal Gold": {"colors": {"bg_from": "#1c1233", "bg_to": "#0b0716", "bg_glow": "#7a5af8", "accent_line": "#e8b923",
                              "button_bg": "#7a3df0", "button_hover": "#9159ff", "text_muted": "#d8c9ff",
                              "burst_bg": "#e8b923", "burst_text": "#1c1233",
                              "confetti_1": "#e8b923", "confetti_2": "#ffffff", "confetti_3": "#7a3df0", "confetti_4": "#ff6bd6"}},
    "Clean Light": {"colors": {"bg_from": "#f4f7ff", "bg_to": "#dfe7ff", "bg_glow": "#9db4ff", "text": "#10163a",
                               "text_muted": "#4a5380", "title": "#10163a", "accent_line": "#2b44ff",
                               "button_bg": "#2b44ff", "button_hover": "#4a5fff", "card_bg": "#ffffff",
                               "button_selected_border": "#10163a", "branding_bg": "#ffffff",
                               "burst_bg": "#ffd814", "burst_text": "#10163a"},
                    "effects": {"swoosh": False}},
}


def deep_merge(base: dict, over: dict) -> dict:
    out = {}
    for k, v in base.items():
        if isinstance(v, dict):
            out[k] = deep_merge(v, (over or {}).get(k) or {}) if isinstance((over or {}).get(k, {}), dict) else dict(v)
        else:
            out[k] = (over or {}).get(k, v)
    return out


def resolve_theme_tokens(raw: str | dict | None) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    return deep_merge(DEFAULT_THEME_TOKENS, raw or {})
