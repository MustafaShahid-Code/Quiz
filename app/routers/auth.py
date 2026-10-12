from fastapi import APIRouter, Depends, HTTPException, Request

from ..db import get_db, now_iso
from ..schemas import LoginIn, PasswordChangeIn, UserCreateIn, UserUpdateIn
from ..security import (current_user, hash_password, record_attempt, require_admin, too_many_failures, create_token,
                        validate_password_strength, verify_password)

router = APIRouter(prefix="/api/admin", tags=["auth"])

# verified against when the username does not exist, so timing does not reveal valid usernames
_DUMMY_HASH = hash_password("dummy-Password-123")


def user_public(u):
    return {"id": u["id"], "username": u["username"], "role": u["role"], "is_active": bool(u["is_active"]),
            "must_change_password": bool(u["must_change_password"]), "last_login_at": u["last_login_at"]}


@router.get("/branding")
def platform_branding(conn=Depends(get_db)):
    """Public: lets the login screen and admin shell show the white-label product name/logo/colour."""
    from ..db import load_settings
    from ..questions import media_url
    s = load_settings(conn)
    return {"product_name": s["admin_product_name"], "client_name": s["client_name"], "primary_color": s["admin_primary_color"],
            "logo_url": media_url(conn, s["admin_logo_asset_id"]), "favicon_url": media_url(conn, s["favicon_asset_id"]),
            "login": {"layout": s["login_layout"], "bg_url": media_url(conn, s["login_bg_asset_id"]), "color_2": s["login_color_2"],
                      "headline": s["login_headline"], "subtext": s["login_subtext"], "features": s["login_features"], "footer": s["login_footer"]}}


@router.post("/login")
def login(body: LoginIn, request: Request, conn=Depends(get_db)):
    if too_many_failures(conn, body.username):
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")
    u = conn.execute("SELECT * FROM admin_users WHERE username=? COLLATE NOCASE", (body.username,)).fetchone()
    ok = verify_password(body.password, u["password_hash"] if u else _DUMMY_HASH)
    ip = request.client.host if request.client else None
    if not (u and ok and u["is_active"]):
        record_attempt(conn, body.username, ip, False)
        raise HTTPException(401, "Invalid username or password")
    record_attempt(conn, body.username, ip, True)
    conn.execute("UPDATE admin_users SET last_login_at=? WHERE id=?", (now_iso(), u["id"]))
    return {"token": create_token(u), "user": user_public(u)}


@router.get("/me")
def me(user=Depends(current_user)):
    return user_public(user)


@router.post("/me/password")
def change_password(body: PasswordChangeIn, user=Depends(current_user), conn=Depends(get_db)):
    if not verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(403, "Current password is incorrect")
    validate_password_strength(body.new_password)
    conn.execute("UPDATE admin_users SET password_hash=?, must_change_password=0 WHERE id=?",
                 (hash_password(body.new_password), user["id"]))
    return {"ok": True}


@router.get("/users")
def list_users(_=Depends(require_admin), conn=Depends(get_db)):
    return [user_public(u) for u in conn.execute("SELECT * FROM admin_users ORDER BY id")]


@router.post("/users", status_code=201)
def create_user(body: UserCreateIn, _=Depends(require_admin), conn=Depends(get_db)):
    validate_password_strength(body.password)
    if conn.execute("SELECT 1 FROM admin_users WHERE username=? COLLATE NOCASE", (body.username,)).fetchone():
        raise HTTPException(409, "Username already exists")
    cur = conn.execute("INSERT INTO admin_users(username,password_hash,role,must_change_password,created_at) VALUES(?,?,?,1,?)",
                       (body.username, hash_password(body.password), body.role, now_iso()))
    return {"id": cur.lastrowid}


@router.put("/users/{uid}")
def update_user(uid: int, body: UserUpdateIn, me=Depends(require_admin), conn=Depends(get_db)):
    u = conn.execute("SELECT * FROM admin_users WHERE id=?", (uid,)).fetchone()
    if not u:
        raise HTTPException(404, "User not found")
    demoting = (body.role and body.role != "admin") or body.is_active is False
    if u["role"] == "admin" and demoting:
        others = conn.execute("SELECT COUNT(*) FROM admin_users WHERE role='admin' AND is_active=1 AND id<>?", (uid,)).fetchone()[0]
        if others == 0:
            raise HTTPException(409, "There must always be at least one active administrator")
    if body.role:
        conn.execute("UPDATE admin_users SET role=? WHERE id=?", (body.role, uid))
    if body.is_active is not None:
        conn.execute("UPDATE admin_users SET is_active=? WHERE id=?", (int(body.is_active), uid))
    if body.password:
        validate_password_strength(body.password)
        conn.execute("UPDATE admin_users SET password_hash=?, must_change_password=1 WHERE id=?",
                     (hash_password(body.password), uid))
    return {"ok": True}


@router.delete("/users/{uid}")
def delete_user(uid: int, me=Depends(require_admin), conn=Depends(get_db)):
    if uid == me["id"]:
        raise HTTPException(409, "You cannot delete your own account")
    u = conn.execute("SELECT * FROM admin_users WHERE id=?", (uid,)).fetchone()
    if not u:
        raise HTTPException(404, "User not found")
    if u["role"] == "admin":
        others = conn.execute("SELECT COUNT(*) FROM admin_users WHERE role='admin' AND is_active=1 AND id<>?", (uid,)).fetchone()[0]
        if others == 0:
            raise HTTPException(409, "There must always be at least one active administrator")
    conn.execute("DELETE FROM admin_users WHERE id=?", (uid,))
    return {"ok": True}
