"""White-label themes: validation of admin-supplied tokens and resolution for the game front-end."""
import json

from fastapi import HTTPException

from .db import DEFAULT_THEME_TOKENS, deep_merge, resolve_theme_tokens
from .schemas import FONT_FAMILY, HEX

BUTTON_STYLES = {"solid", "outline", "glass"}


def sanitize_tokens(tokens: dict) -> dict:
    """Merge over defaults and strictly validate every value (these end up inside CSS)."""
    if not isinstance(tokens, dict):
        raise HTTPException(422, "tokens must be an object")
    merged = deep_merge(DEFAULT_THEME_TOKENS, tokens)
    for k, v in merged["colors"].items():
        if not isinstance(v, str) or not HEX.match(v):
            raise HTTPException(422, f"colors.{k} must be a hex colour such as #0a1cff")
    for k in ("family_en", "family_ar"):
        v = merged["fonts"][k]
        if not isinstance(v, str) or not FONT_FAMILY.match(v):
            raise HTTPException(422, f"fonts.{k} contains unsupported characters")
    for k in ("button_radius", "card_radius"):
        v = merged["shape"][k]
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= 60:
            raise HTTPException(422, f"shape.{k} must be a number between 0 and 60")
    if merged["shape"]["button_style"] not in BUTTON_STYLES:
        raise HTTPException(422, "shape.button_style must be solid, outline or glass")
    for k, v in merged["assets"].items():
        if v is not None and (not isinstance(v, int) or isinstance(v, bool)):
            raise HTTPException(422, f"assets.{k} must be an asset id or null")
    fid = merged["fonts"]["font_asset_id"]
    if fid is not None and (not isinstance(fid, int) or isinstance(fid, bool)):
        raise HTTPException(422, "fonts.font_asset_id must be an asset id or null")
    e = merged["effects"]
    ov = e["background_overlay"]
    if not isinstance(ov, (int, float)) or isinstance(ov, bool) or not 0 <= ov <= 0.9:
        raise HTTPException(422, "effects.background_overlay must be between 0 and 0.9")
    for k in ("swoosh", "confetti", "stadium_lights"):
        if not isinstance(e[k], bool):
            raise HTTPException(422, f"effects.{k} must be true or false")
    return merged


def check_assets_exist(conn, tokens: dict):
    ids = [v for v in tokens["assets"].values() if v] + ([tokens["fonts"]["font_asset_id"]] if tokens["fonts"]["font_asset_id"] else [])
    for i in ids:
        if not conn.execute("SELECT 1 FROM media_assets WHERE id=?", (i,)).fetchone():
            raise HTTPException(422, f"asset {i} does not exist")


def asset_url(conn, asset_id):
    if not asset_id:
        return None
    r = conn.execute("SELECT filename FROM media_assets WHERE id=?", (asset_id,)).fetchone()
    return f"/media/{r['filename']}" if r else None


def resolve_for_game(conn, row) -> dict:
    tokens = resolve_theme_tokens(row["tokens"])
    out = json.loads(json.dumps(tokens))
    out["urls"] = {
        "logo_left": asset_url(conn, tokens["assets"]["logo_left_asset_id"]),
        "logo_right": asset_url(conn, tokens["assets"]["logo_right_asset_id"]),
        "background": asset_url(conn, tokens["assets"]["background_asset_id"]),
        "font": asset_url(conn, tokens["fonts"]["font_asset_id"]),
    }
    out["id"], out["name"] = row["id"], row["name"]
    return out
