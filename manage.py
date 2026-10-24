#!/usr/bin/env python3
"""Management commands:  migrate | create-admin | reset-password | seed | status"""
import argparse
import getpass
import sys

from app import db, seed
from app.security import hash_password, validate_password_strength
from fastapi import HTTPException


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="apply database migrations")
    sub.add_parser("seed", help="insert sample content (only if never seeded)")
    sub.add_parser("status", help="show schema version and row counts")
    ca = sub.add_parser("create-admin", help="create an administrator")
    ca.add_argument("username")
    ca.add_argument("--role", default="admin", choices=["admin", "editor", "viewer"])
    rp = sub.add_parser("reset-password", help="set a new password for an existing user")
    rp.add_argument("username")
    a = ap.parse_args()

    conn = db.connect()
    try:
        applied = db.migrate(conn)
        if a.cmd == "migrate":
            print("applied migrations:", applied or "none (already up to date)")
        elif a.cmd == "seed":
            seed.seed_content(conn)
            print("seed complete")
        elif a.cmd == "status":
            v = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            print("schema version:", v)
            for t in ("admin_users", "questions", "answer_options", "media_assets", "characters", "themes", "brand_slides", "game_sessions"):
                print(f"  {t}: {conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}")
        else:
            pw = getpass.getpass("Password: ")
            if pw != getpass.getpass("Repeat password: "):
                sys.exit("Passwords do not match")
            try:
                validate_password_strength(pw)
            except HTTPException as e:
                sys.exit(e.detail)
            if a.cmd == "create-admin":
                conn.execute("INSERT INTO admin_users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
                             (a.username, hash_password(pw), a.role, db.now_iso()))
                print("created", a.username)
            else:
                n = conn.execute("UPDATE admin_users SET password_hash=?, must_change_password=0, is_active=1 WHERE username=? COLLATE NOCASE",
                                 (hash_password(pw), a.username)).rowcount
                print("password updated" if n else "no such user")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
