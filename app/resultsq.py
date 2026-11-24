"""Shared helpers for querying finished/played rounds (results list, CSV export, analytics)."""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from .security import ensure_game, game_clause


def day_start_utc(day: str, tz_min: int, plus_days: int = 0) -> str:
    """Local calendar day (YYYY-MM-DD, browser time zone = UTC + tz_min minutes) -> UTC ISO string for comparing with started_at."""
    try:
        d = datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(422, "Dates must look like 2026-11-01")
    return (d + timedelta(days=plus_days) - timedelta(minutes=tz_min)).replace(tzinfo=timezone.utc).isoformat(timespec="milliseconds")


def clamp_tz(tz) -> int:
    try:
        return max(-720, min(840, int(tz)))
    except (TypeError, ValueError):
        return 0


def session_filters(conn, user, game_id=None, lang="", outcome="", date_from="", date_to="", q="", tz=0, claimed="", alias=""):
    """-> (WHERE sql, args) for game_sessions, honouring the staff member's game access."""
    conds, args = [], []
    a = alias + "." if alias else ""
    if game_id:
        ensure_game(conn, user, game_id)
    sc, sa = game_clause(conn, user, column=a + "game_id")
    if sc:
        conds.append(sc[5:]); args += sa
    if game_id:
        conds.append(f"{a}game_id=?"); args.append(game_id)
    if lang in ("en", "ar"):
        conds.append(f"{a}lang=?"); args.append(lang)
    if outcome in ("win", "lose"):
        conds.append(f"{a}outcome=?"); args.append(outcome)
    elif outcome == "none":
        conds.append(f"{a}outcome IS NULL")
    tz = clamp_tz(tz)
    if date_from:
        conds.append(f"{a}started_at>=?"); args.append(day_start_utc(date_from, tz))
    if date_to:
        conds.append(f"{a}started_at<?"); args.append(day_start_utc(date_to, tz, 1))
    if q.strip():
        conds.append(f"{a}player_name LIKE ? ESCAPE '\\'")
        args.append("%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if claimed == "yes":
        conds.append(f"{a}claimed_at IS NOT NULL")
    elif claimed == "no":
        conds.append(f"{a}claim_code IS NOT NULL AND {a}claimed_at IS NULL")
    return (("WHERE " + " AND ".join(conds)) if conds else ""), args
