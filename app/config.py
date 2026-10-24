"""Runtime configuration. Values are read from the environment at call time so tests can reconfigure."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
_override: dict = {}


def configure(data_dir=None, env=None):
    _override.clear()
    if data_dir is not None:
        _override["data_dir"] = Path(data_dir)
    if env is not None:
        _override["env"] = env


def data_dir() -> Path:
    p = _override.get("data_dir") or Path(os.environ.get("FQ_DATA_DIR", BASE_DIR / "data"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def upload_dir() -> Path:
    p = data_dir() / "uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return data_dir() / "quiz.db"


def env() -> str:
    return _override.get("env") or os.environ.get("FQ_ENV", "development")


def is_dev() -> bool:
    return env() == "development"


def jwt_secret() -> str:
    """Persisted random secret (override with FQ_JWT_SECRET)."""
    if os.environ.get("FQ_JWT_SECRET"):
        return os.environ["FQ_JWT_SECRET"]
    f = data_dir() / "jwt_secret.key"
    if not f.exists():
        f.write_text(secrets.token_urlsafe(48))
        try:
            f.chmod(0o600)
        except OSError:
            pass
    return f.read_text().strip()


TOKEN_TTL_HOURS = int(os.environ.get("FQ_TOKEN_TTL_HOURS", "12"))
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 300
