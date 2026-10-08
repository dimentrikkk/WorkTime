"""Employee self-service portal routes."""
import os
import uuid
import base64
from datetime import datetime, date

from flask import (
    Blueprint, render_template, session, abort, send_from_directory,
    current_app, request, redirect, url_for, flash, jsonify,
)

from ..db import get_db
from ..services.auth_service import employee_required, hash_password, verify_password
from ..services.attendance_service import format_minutes
from ..services.salary_service import compute_salary
from ..services.notification_service import (
    notify, list_for, mark_all_read, unread_count,
)
from ..services.vacation_service import balance, count_business_days

bp = Blueprint("employee", __name__, url_prefix="/funcionario")

DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def _me():
    fid = session.get("user_id")
    if not fid or session.get("user_type") != "funcionario":
        abort(403)
    db = get_db()
    return db.execute(
        """SELECT f.*, d.nome AS departamento_nome
             FROM funcionarios f
             LEFT JOIN departamentos d ON d.id = f.departamento_id
            WHERE f.id = ?""",
        (fid,),
    ).fetchone()


# ----------------------------- Dashboard -----------------------------
@bp.route("/")
@bp.route("/dashboard")
@employee_required
def dashboard():
    func = _me()
    db = get_db()
    today = date.today()

    sessoes_mes = db.execute(
        """SELECT COALESCE(SUM(total_minutos),0) AS m
             FROM sessoes_trabalho
            WHERE funcionario_id = ?
              AND CAST(strftime('%Y', data) AS INT) = ?
              AND CAST(strftime('%m', data) AS INT) = ?""",
        (func["id"], today.year, today.month),
    ).fetchone()
    minutos_mes = int(sessoes_mes["m"] or 0)

    ultimos_registos = db.execute(
        """SELECT tipo, timestamp FROM registos_ponto
            WHERE funcionario_id = ? ORDER BY timestamp DESC LIMIT 10""",
        (func["id"],),
    ).fetchall()

    salario = compute_salary(func["id"], today.year, today.month)
    open_sess = db.execute(
        "SELECT * FROM sessoes_trabalho WHERE funcionario_id = ? AND hora_saida IS NULL ORDER BY hora_entrada DESC LIMIT 1",
        (func["id"],),
    ).fetchone()

    ferias = balance(func, today.year)
    notifs = list_for("funcionario", func["id"], limit=5)

    return render_template(
        "employee/dashboard.html",
        func=func,
        minutos_mes=minutos_mes,
        horas_mes=format_minutes(minutos_mes),
        ultimos_registos=ultimos_registos,
        salario=salario,
        open_sess=open_sess,
        ferias=ferias,
        notifs=notifs,
        format_minutes=format_minutes,
    )


@bp.route("/registos")
@employee_required
def registos():
    func = _me()
    db = get_db()
    rows = db.execute(
        """SELECT * FROM sessoes_trabalho
            WHERE funcionario_id = ? ORDER BY hora_entrada DESC LIMIT 60""",
        (func["id"],),
    ).fetchall()
    return render_template("employee/registos.html", func=func, rows=rows, format_minutes=format_minutes)


@bp.route("/horario")
@employee_required
def horario():
    func = _me()
    db = get_db()
    rows = db.execute(
        "SELECT * FROM horarios WHERE funcionario_id = ? ORDER BY dia_semana",
        (func["id"],),
    ).fetchall()
    by_day = {r["dia_semana"]: r for r in rows}
    return render_template("employee/horario.html", func=func, by_day=by_day, dias=DIAS)


@bp.route("/salario")
@employee_required
def salario():
    func = _me()
    today = date.today()
    info = compute_salary(func["id"], today.year, today.month)
    return render_template("employee/salario.html", func=func, info=info, hoje=today)


@bp.route("/faltas")
@employee_required
def faltas():
    func = _me()
    db = get_db()
    rows = db.execute(
        "SELECT * FROM faltas WHERE funcionario_id = ? ORDER BY data DESC",
        (func["id"],),
    ).fetchall()
    return render_template("employee/faltas.html", func=func, rows=rows)


# ----------------------------- Justificações de falta -----------------------------
@bp.route("/justificacoes", methods=["GET", "POST"])
@employee_required
def justificacoes():
    func = _me()
    db = get_db()
    if request.method == "POST":
        di = request.form.get("data_inicio")
        df = request.form.get("data_fim") or di
        motivo = (request.form.get("motivo") or "").strip()
        if not di or not motivo:
            flash("Indique a data e o motivo.", "error")
        else:
            db.execute(
                """INSERT INTO pedidos_falta (funcionario_id, data_inicio, data_fim, motivo)
                   VALUES (?,?,?,?)""",
                (func["id"], di, df, motivo),
            )
            db.commit()
            notify("admin", None, "Pedido de justificação de falta",
                   f"{func['nome_completo']} pediu justificação para {di}" + (f"–{df}" if df != di else "")
                   + f": {motivo}", "info")
            flash("Pedido enviado. Aguarde a decisão do administrador.", "success")
            return redirect(url_for("employee.justificacoes"))

    rows = db.execute(
        "SELECT * FROM pedidos_falta WHERE funcionario_id = ? ORDER BY created_at DESC",
        (func["id"],),
    ).fetchall()
    return render_template("employee/justificacoes.html", func=func, rows=rows)


# ----------------------------- Férias -----------------------------
@bp.route("/ferias", methods=["GET", "POST"])
@employee_required
def ferias():
    func = _me()
    db = get_db()
    today = date.today()

    if request.method == "POST":
        try:
            di = date.fromisoformat(request.form.get("data_inicio") or "")
            df = date.fromisoformat(request.form.get("data_fim") or "")
            motivo = (request.form.get("motivo") or "").strip()
            if df < di:
                raise ValueError("Data fim antes do início.")
            dias = count_business_days(di, df)
            if dias <= 0:
                raise ValueError("Período inválido (sem dias úteis).")
            db.execute(
                """INSERT INTO pedidos_ferias (funcionario_id, data_inicio, data_fim, dias, motivo)
                   VALUES (?,?,?,?,?)""",
                (func["id"], di.isoformat(), df.isoformat(), dias, motivo or None),
            )
            db.commit()
            notify("admin", None, "Pedido de férias",
                   f"{func['nome_completo']} pediu {dias} dias de férias ({di} a {df}).", "info")
            flash(f"Pedido de {dias} dias enviado.", "success")
            return redirect(url_for("employee.ferias"))
        except Exception as e:
            flash(f"Erro: {e}", "error")

    bal = balance(func, today.year)
    rows = db.execute(
        "SELECT * FROM pedidos_ferias WHERE funcionario_id = ? ORDER BY created_at DESC",
        (func["id"],),
    ).fetchall()
    return render_template("employee/ferias.html", func=func, balance=bal, rows=rows)


# ----------------------------- Notificações -----------------------------
@bp.route("/notificacoes")
@employee_required
def notificacoes():
    func = _me()
    rows = list_for("funcionario", func["id"], limit=100)
    mark_all_read("funcionario", func["id"])
    return render_template("employee/notificacoes.html", func=func, rows=rows)


@bp.route("/notificacoes/badge")
@employee_required
def notificacoes_badge():
    return jsonify({"unread": unread_count("funcionario", session["user_id"])})


# ----------------------------- Perfil (foto + password) -----------------------------
@bp.route("/perfil", methods=["GET", "POST"])
@employee_required
def perfil():
    func = _me()
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "password":
            atual = request.form.get("atual") or ""
            nova = request.form.get("nova") or ""
            if not verify_password(atual, func["password_hash"]):
                flash("Password atual incorreta.", "error")
            elif len(nova) < 6:
                flash("A nova password deve ter pelo menos 6 caracteres.", "error")
            else:
                db.execute("UPDATE funcionarios SET password_hash = ? WHERE id = ?",
                           (hash_password(nova), func["id"]))
                db.commit()
                flash("Password alterada.", "success")
        elif action == "foto":
            data_url = request.form.get("foto_data") or ""
            if data_url.startswith("data:image"):
                _save_avatar(func["id"], data_url)
                flash("Foto de perfil atualizada.", "success")
            else:
                flash("Imagem inválida.", "error")
        return redirect(url_for("employee.perfil"))
    return render_template("employee/perfil.html", func=func)


def _save_avatar(funcionario_id: int, data_url: str) -> str:
    header, b64 = data_url.split(",", 1)
    ext = "png" if "png" in header else "jpg"
    name = f"avatar_{funcionario_id}_{uuid.uuid4().hex[:8]}.{ext}"
    path = os.path.join(current_app.config["UPLOAD_DIR"], name)
    with open(path, "wb") as fh:
        fh.write(base64.b64decode(b64))
    db = get_db()
    db.execute("UPDATE funcionarios SET foto_perfil = ? WHERE id = ?", (name, funcionario_id))
    db.commit()
    return name


@bp.route("/uploads/<path:filename>")
@employee_required
def uploads(filename):
    return send_from_directory(current_app.config["UPLOAD_DIR"], filename)
