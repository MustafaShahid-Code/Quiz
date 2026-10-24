"""Password hashing, JWT issuing and role-based authorisation."""
import time
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request

from . import config
from .db import get_db

ROLE_RANK = {"viewer": 1, "editor": 2, "admin": 3}


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8")[:72], bcrypt.gensalt(rounds=12)).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8")[:72], hashed.encode())
    except ValueError:
        return False


def validate_password_strength(pw: str):
    if len(pw) < 10:
        raise HTTPException(422, "Password must be at least 10 characters long")
    if pw.lower() == pw or pw.upper() == pw or not any(c.isdigit() for c in pw):
        raise HTTPException(422, "Password must mix upper and lower case letters and include a digit")


def create_token(user) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=config.TOKEN_TTL_HOURS)
    return jwt.encode({"sub": str(user["id"]), "role": user["role"], "exp": exp, "typ": "admin"},
                      config.jwt_secret(), algorithm="HS256")


def decode_token(token: str) -> dict:
    try:
        data = jwt.decode(token, config.jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")
    if data.get("typ") != "admin":
        raise HTTPException(401, "Invalid token")
    return data


def user_from_token(token: str, conn):
    data = decode_token(token)
    row = conn.execute("SELECT * FROM admin_users WHERE id=?", (int(data["sub"]),)).fetchone()
    if not row or not row["is_active"]:
        raise HTTPException(401, "Account disabled or removed")
    return row


def current_user(request: Request, conn=Depends(get_db)):
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "Authentication required")
    return user_from_token(auth[7:].strip(), conn)


def require_role(minimum: str):
    def dep(user=Depends(current_user)):
        if ROLE_RANK[user["role"]] < ROLE_RANK[minimum]:
            raise HTTPException(403, "Your role does not allow this action")
        return user
    return dep


require_viewer = require_role("viewer")
require_editor = require_role("editor")
require_admin = require_role("admin")


# --- login throttling -------------------------------------------------------------------------
def too_many_failures(conn, username: str) -> bool:
    since = time.time() - config.LOGIN_WINDOW_SECONDS
    n = conn.execute("SELECT COUNT(*) FROM login_attempts WHERE username=? AND success=0 AND at>?",
                     (username.lower(), since)).fetchone()[0]
    return n >= config.LOGIN_MAX_FAILURES


def record_attempt(conn, username: str, ip: str | None, success: bool):
    conn.execute("INSERT INTO login_attempts(username, ip, success, at) VALUES (?,?,?,?)",
                 (username.lower(), ip, int(success), time.time()))
    if success:
        conn.execute("DELETE FROM login_attempts WHERE username=? AND success=0", (username.lower(),))
    conn.execute("DELETE FROM login_attempts WHERE at < ?", (time.time() - 86400,))


# --- per-game access ---------------------------------------------------------------------------
def allowed_games(conn, user):
    """None = every game. Otherwise the set of game ids this staff member may work on (admins always get everything)."""
    if user["role"] == "admin" or user["all_games"]:
        return None
    return {r[0] for r in conn.execute("SELECT game_id FROM user_games WHERE user_id=?", (user["id"],))}


def ensure_game(conn, user, game_id):
    ok = allowed_games(conn, user)
    if ok is not None and game_id not in ok:
        raise HTTPException(403, "Your account does not have access to this game")


def game_clause(conn, user, column="game_id"):
    """SQL fragment + args that restrict a query to the user's games ('' when unrestricted)."""
    ok = allowed_games(conn, user)
    if ok is None:
        return "", []
    if not ok:
        return f" AND {column} IN (NULL)", []
    return f" AND {column} IN ({','.join('?' * len(ok))})", sorted(ok)


# --- game access password (players type only a password, no username) ------------------------------
GAME_TOKEN_HOURS = 12


def game_pw_fingerprint(game) -> str:
    """Changes whenever the password changes, so old unlock tokens stop working immediately."""
    import hashlib
    return hashlib.sha256((game["access_password_hash"] or "").encode()).hexdigest()[:16]


def create_game_token(game) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=GAME_TOKEN_HOURS)
    return jwt.encode({"gid": game["id"], "pv": game_pw_fingerprint(game), "exp": exp, "typ": "game"},
                      config.jwt_secret(), algorithm="HS256")


def game_token_valid(token: str | None, game) -> bool:
    if not token:
        return False
    try:
        d = jwt.decode(token, config.jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return False
    return d.get("typ") == "game" and d.get("gid") == game["id"] and d.get("pv") == game_pw_fingerprint(game)


def game_pw_throttle_key(game) -> str:
    return f"game:{game['id']}"
