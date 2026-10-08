"""Flask application factory."""
from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, redirect, url_for, session

from .config import Config
from .db import init_db, seed_initial_data


def create_app() -> Flask:
    app = Flask(
        __name__,
        static_folder="static",
        template_folder="templates",
    )
    app.config.from_object(Config)

    # Ensure data dirs exist
    Path(Config.DATA_DIR).mkdir(parents=True, exist_ok=True)
    Path(Config.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

    # Initialise DB and seed defaults (admin, departamentos)
    with app.app_context():
        init_db()
        seed_initial_data()

    # Register blueprints
    from .routes.auth import bp as auth_bp
    from .routes.kiosk import bp as kiosk_bp
    from .routes.admin import bp as admin_bp
    from .routes.employee import bp as employee_bp
    from .routes.api import bp as api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(kiosk_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(employee_bp)
    app.register_blueprint(api_bp)

    @app.route("/")
    def index():
        if session.get("user_type") == "admin":
            return redirect(url_for("admin.dashboard"))
        if session.get("user_type") == "funcionario":
            return redirect(url_for("employee.dashboard"))
        return redirect(url_for("auth.login"))

    @app.context_processor
    def inject_globals():
        from .services.notification_service import unread_count
        utype = session.get("user_type")
        uid = session.get("user_id")
        unread = 0
        avatar = None
        if utype == "funcionario":
            unread = unread_count("funcionario", uid)
            from .db import get_db
            row = get_db().execute(
                "SELECT foto_perfil FROM funcionarios WHERE id = ?", (uid,)
            ).fetchone()
            avatar = row["foto_perfil"] if row else None
        elif utype == "admin":
            unread = unread_count("admin", None)
        return {
            "current_user_type": utype,
            "current_user_name": session.get("user_name"),
            "current_user_id": uid,
            "unread_notifs": unread,
            "current_avatar": avatar,
        }

    return app
