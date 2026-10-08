"""Authentication helpers."""
from __future__ import annotations

from functools import wraps
from typing import Optional

import bcrypt
from flask import session, redirect, url_for, flash, request

from ..db import get_db


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def authenticate(email: str, password: str) -> Optional[dict]:
    """Return a user dict on success or None."""
    db = get_db()
    row = db.execute(
        "SELECT id, nome, email, password_hash FROM admins WHERE email = ?",
        (email,),
    ).fetchone()
    if row and verify_password(password, row["password_hash"]):
        return {"id": row["id"], "nome": row["nome"], "email": row["email"], "tipo": "admin"}

    row = db.execute(
        "SELECT id, nome_completo AS nome, email, password_hash, ativo FROM funcionarios WHERE email = ?",
        (email,),
    ).fetchone()
    if row and row["ativo"] and verify_password(password, row["password_hash"]):
        return {"id": row["id"], "nome": row["nome"], "email": row["email"], "tipo": "funcionario"}

    return None


def record_login_attempt(email: str, success: bool, ip: Optional[str] = None) -> None:
    db = get_db()
    db.execute(
        "INSERT INTO login_attempts (email, success, ip) VALUES (?, ?, ?)",
        (email, 1 if success else 0, ip),
    )
    db.commit()


def is_locked(email: str, max_attempts: int = 5, window_minutes: int = 15) -> bool:
    """True if there are too many failed attempts within the window."""
    db = get_db()
    row = db.execute(
        f"""SELECT COUNT(*) AS c FROM login_attempts
            WHERE email = ? AND success = 0
              AND created_at > datetime('now', '-{int(window_minutes)} minutes')""",
        (email,),
    ).fetchone()
    return int(row["c"] or 0) >= max_attempts


def login_user(user: dict) -> None:
    session.clear()
    session["user_id"] = user["id"]
    session["user_type"] = user["tipo"]
    session["user_name"] = user["nome"]
    session.permanent = True


def logout_user() -> None:
    session.clear()


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if session.get("user_type") != "admin":
            flash("Acesso restrito a administradores.", "error")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def employee_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if session.get("user_type") != "funcionario":
            flash("Acesso restrito a funcionários.", "error")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapper
