"""Login / logout routes."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from ..services.auth_service import (
    authenticate, login_user, logout_user, record_login_attempt, is_locked,
)
from ..services.notification_service import notify

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_type") == "admin":
        return redirect(url_for("admin.dashboard"))
    if session.get("user_type") == "funcionario":
        return redirect(url_for("employee.dashboard"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        if not email or not password:
            flash("Preencha o email e a password.", "error")
            return render_template("login.html"), 400
        if is_locked(email):
            flash("Conta temporariamente bloqueada por excesso de tentativas. Tente novamente em 15 minutos.", "error")
            return render_template("login.html"), 429
        user = authenticate(email, password)
        ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        record_login_attempt(email, success=bool(user), ip=ip)
        if not user:
            notify("admin", None, "Tentativa de login falhada",
                   f"Email: {email} (IP {ip or '?'})", "warn")
            flash("Credenciais inválidas.", "error")
            return render_template("login.html"), 401
        login_user(user)
        if user["tipo"] == "admin":
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("employee.dashboard"))
    return render_template("login.html")


@bp.route("/logout")
def logout():
    logout_user()
    flash("Sessão terminada.", "success")
    return redirect(url_for("auth.login"))
