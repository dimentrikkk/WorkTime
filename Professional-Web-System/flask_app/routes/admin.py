"""Admin panel routes."""
from datetime import datetime, date, timedelta

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session,
    send_from_directory, current_app, jsonify, abort,
)

from ..db import get_db
from ..services.auth_service import admin_required, hash_password
from ..services.attendance_service import format_minutes
from ..services.salary_service import compute_salary, persist_salary
from ..services.notification_service import notify, list_for, mark_all_read
from ..services.vacation_service import balance

bp = Blueprint("admin", __name__, url_prefix="/admin")

CARGOS = [
    ("armazem", "Armazém"),
    ("camionista", "Camionista"),
    ("vendedor", "Vendedor"),
    ("secretaria", "Secretária"),
]
DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


# ----------------------------- Dashboard -----------------------------
@bp.route("/")
@bp.route("/dashboard")
@admin_required
def dashboard():
    db = get_db()
    today = date.today()
    total_func = db.execute("SELECT COUNT(*) AS c FROM funcionarios WHERE ativo = 1").fetchone()["c"]
    presentes = db.execute(
        "SELECT COUNT(DISTINCT funcionario_id) AS c FROM sessoes_trabalho WHERE date(hora_entrada) = ? AND hora_saida IS NULL",
        (today.isoformat(),),
    ).fetchone()["c"]

    minutos_hoje = db.execute(
        "SELECT COALESCE(SUM(total_minutos),0) AS m FROM sessoes_trabalho WHERE data = ?",
        (today.isoformat(),),
    ).fetchone()["m"]

    faltas_mes = db.execute(
        """SELECT COUNT(*) AS c FROM faltas
            WHERE CAST(strftime('%Y', data) AS INT) = ?
              AND CAST(strftime('%m', data) AS INT) = ?""",
        (today.year, today.month),
    ).fetchone()["c"]

    ultimos = db.execute(
        """SELECT r.tipo, r.timestamp, f.nome_completo, f.cargo
             FROM registos_ponto r
             JOIN funcionarios f ON f.id = r.funcionario_id
            ORDER BY r.timestamp DESC LIMIT 10"""
    ).fetchall()

    # Charts: presences last 7 days
    presencas_7d = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        c = db.execute(
            "SELECT COUNT(DISTINCT funcionario_id) AS c FROM sessoes_trabalho WHERE data = ?",
            (day.isoformat(),),
        ).fetchone()["c"]
        presencas_7d.append({"data": day.isoformat(), "presencas": c})

    cargos_count = db.execute(
        "SELECT cargo, COUNT(*) AS c FROM funcionarios WHERE ativo = 1 GROUP BY cargo"
    ).fetchall()

    return render_template(
        "admin/dashboard.html",
        total_func=total_func,
        presentes=presentes,
        horas_hoje=format_minutes(minutos_hoje),
        faltas_mes=faltas_mes,
        ultimos=ultimos,
        presencas_7d=presencas_7d,
        cargos_count=cargos_count,
    )


# ----------------------------- Funcionários -----------------------------
@bp.route("/funcionarios")
@admin_required
def funcionarios_list():
    db = get_db()
    q = (request.args.get("q") or "").strip()
    cargo = request.args.get("cargo") or ""
    sql = """SELECT f.*, d.nome AS departamento_nome,
                    (SELECT COUNT(*) FROM face_encodings fe WHERE fe.funcionario_id = f.id) AS amostras_face
               FROM funcionarios f
               LEFT JOIN departamentos d ON d.id = f.departamento_id
              WHERE 1=1"""
    args = []
    if q:
        sql += " AND (f.nome_completo LIKE ? OR f.email LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if cargo:
        sql += " AND f.cargo = ?"
        args.append(cargo)
    sql += " ORDER BY f.nome_completo"
    rows = db.execute(sql, args).fetchall()
    return render_template("admin/funcionarios_list.html", rows=rows, cargos=CARGOS, q=q, cargo=cargo)


@bp.route("/funcionarios/novo", methods=["GET", "POST"])
@admin_required
def funcionarios_new():
    db = get_db()
    departamentos = db.execute("SELECT * FROM departamentos ORDER BY nome").fetchall()

    if request.method == "POST":
        f = request.form
        try:
            db.execute(
                """INSERT INTO funcionarios
                   (nome_completo, idade, email, telefone, nif, data_nascimento, data_admissao,
                    tipo_contrato, morada, cidade, codigo_postal, cargo, departamento_id,
                    salario_hora, dias_ferias_ano, notas, password_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    f.get("nome_completo", "").strip(),
                    int(f.get("idade") or 0) or None,
                    f.get("email", "").strip().lower(),
                    f.get("telefone", "").strip() or None,
                    f.get("nif", "").strip() or None,
                    f.get("data_nascimento") or None,
                    f.get("data_admissao") or None,
                    f.get("tipo_contrato") or None,
                    f.get("morada", "").strip() or None,
                    f.get("cidade", "").strip() or None,
                    f.get("codigo_postal", "").strip() or None,
                    f.get("cargo"),
                    int(f.get("departamento_id")) if f.get("departamento_id") else None,
                    float(f.get("salario_hora") or 0),
                    int(f.get("dias_ferias_ano") or 22),
                    f.get("notas", "").strip() or None,
                    hash_password(f.get("password") or "changeme"),
                ),
            )
            db.commit()
            new_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            flash("Funcionário cadastrado. Capture agora as imagens faciais.", "success")
            return redirect(url_for("admin.funcionarios_face", fid=new_id))
        except Exception as e:
            flash(f"Erro ao cadastrar: {e}", "error")

    return render_template("admin/funcionarios_form.html", func=None, departamentos=departamentos, cargos=CARGOS)


@bp.route("/funcionarios/<int:fid>", methods=["GET", "POST"])
@admin_required
def funcionarios_edit(fid: int):
    db = get_db()
    func = db.execute("SELECT * FROM funcionarios WHERE id = ?", (fid,)).fetchone()
    if not func:
        abort(404)
    departamentos = db.execute("SELECT * FROM departamentos ORDER BY nome").fetchall()

    if request.method == "POST":
        f = request.form
        new_pw = (f.get("password") or "").strip()
        try:
            db.execute(
                """UPDATE funcionarios SET
                       nome_completo = ?, idade = ?, email = ?, telefone = ?, nif = ?,
                       data_nascimento = ?, data_admissao = ?, tipo_contrato = ?,
                       morada = ?, cidade = ?, codigo_postal = ?,
                       cargo = ?, departamento_id = ?, salario_hora = ?,
                       dias_ferias_ano = ?, notas = ?, ativo = ?
                   WHERE id = ?""",
                (
                    f.get("nome_completo", "").strip(),
                    int(f.get("idade") or 0) or None,
                    f.get("email", "").strip().lower(),
                    f.get("telefone", "").strip() or None,
                    f.get("nif", "").strip() or None,
                    f.get("data_nascimento") or None,
                    f.get("data_admissao") or None,
                    f.get("tipo_contrato") or None,
                    f.get("morada", "").strip() or None,
                    f.get("cidade", "").strip() or None,
                    f.get("codigo_postal", "").strip() or None,
                    f.get("cargo"),
                    int(f.get("departamento_id")) if f.get("departamento_id") else None,
                    float(f.get("salario_hora") or 0),
                    int(f.get("dias_ferias_ano") or 22),
                    f.get("notas", "").strip() or None,
                    1 if f.get("ativo") == "on" else 0,
                    fid,
                ),
            )
            if new_pw:
                db.execute("UPDATE funcionarios SET password_hash = ? WHERE id = ?", (hash_password(new_pw), fid))
            db.commit()
            flash("Funcionário atualizado.", "success")
            return redirect(url_for("admin.funcionarios_list"))
        except Exception as e:
            flash(f"Erro: {e}", "error")

    return render_template("admin/funcionarios_form.html", func=func, departamentos=departamentos, cargos=CARGOS)


@bp.route("/funcionarios/<int:fid>/delete", methods=["POST"])
@admin_required
def funcionarios_delete(fid: int):
    db = get_db()
    db.execute("DELETE FROM funcionarios WHERE id = ?", (fid,))
    db.commit()
    flash("Funcionário removido.", "success")
    return redirect(url_for("admin.funcionarios_list"))


@bp.route("/funcionarios/<int:fid>/face")
@admin_required
def funcionarios_face(fid: int):
    db = get_db()
    func = db.execute("SELECT * FROM funcionarios WHERE id = ?", (fid,)).fetchone()
    if not func:
        abort(404)
    samples = db.execute(
        "SELECT COUNT(*) AS c FROM face_encodings WHERE funcionario_id = ?",
        (fid,),
    ).fetchone()["c"]
    return render_template("admin/funcionarios_face.html", func=func, samples=samples)


# ----------------------------- Horários -----------------------------
@bp.route("/horarios", methods=["GET", "POST"])
@admin_required
def horarios():
    db = get_db()
    funcionarios = db.execute("SELECT id, nome_completo FROM funcionarios WHERE ativo = 1 ORDER BY nome_completo").fetchall()

    selected_id = request.values.get("funcionario_id", type=int)
    if request.method == "POST" and selected_id:
        # Replace all existing schedule for this employee
        db.execute("DELETE FROM horarios WHERE funcionario_id = ?", (selected_id,))
        for d in range(7):
            entrada = request.form.get(f"entrada_{d}")
            saida = request.form.get(f"saida_{d}")
            if entrada and saida:
                db.execute(
                    "INSERT INTO horarios (funcionario_id, dia_semana, hora_entrada, hora_saida) VALUES (?, ?, ?, ?)",
                    (selected_id, d, entrada, saida),
                )
        db.commit()
        notify("funcionario", selected_id,
               "Horário atualizado",
               "O administrador alterou o seu horário semanal. Consulte a página Horário para ver os novos turnos.",
               "info")
        flash("Horário atualizado e funcionário notificado.", "success")
        return redirect(url_for("admin.horarios", funcionario_id=selected_id))

    horario_rows = []
    if selected_id:
        horario_rows = db.execute(
            "SELECT * FROM horarios WHERE funcionario_id = ? ORDER BY dia_semana",
            (selected_id,),
        ).fetchall()
    by_day = {r["dia_semana"]: r for r in horario_rows}
    return render_template("admin/horarios.html", funcionarios=funcionarios, selected_id=selected_id, by_day=by_day, dias=DIAS)


# ----------------------------- Registos de ponto -----------------------------
@bp.route("/registos")
@admin_required
def registos():
    db = get_db()
    func_id = request.args.get("funcionario_id", type=int)
    sql = """SELECT r.*, f.nome_completo, f.cargo
               FROM registos_ponto r
               JOIN funcionarios f ON f.id = r.funcionario_id
              WHERE 1=1"""
    args = []
    if func_id:
        sql += " AND r.funcionario_id = ?"
        args.append(func_id)
    sql += " ORDER BY r.timestamp DESC LIMIT 200"
    rows = db.execute(sql, args).fetchall()
    funcionarios = db.execute("SELECT id, nome_completo FROM funcionarios ORDER BY nome_completo").fetchall()
    return render_template("admin/registos.html", rows=rows, funcionarios=funcionarios, func_id=func_id)


# ----------------------------- Faltas -----------------------------
@bp.route("/faltas", methods=["GET", "POST"])
@admin_required
def faltas():
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            try:
                db.execute(
                    "INSERT INTO faltas (funcionario_id, data, justificada, motivo) VALUES (?, ?, ?, ?)",
                    (
                        int(request.form["funcionario_id"]),
                        request.form["data"],
                        1 if request.form.get("justificada") == "on" else 0,
                        request.form.get("motivo", ""),
                    ),
                )
                db.commit()
                flash("Falta registada.", "success")
            except Exception as e:
                flash(f"Erro: {e}", "error")
        elif action == "delete":
            db.execute("DELETE FROM faltas WHERE id = ?", (int(request.form["id"]),))
            db.commit()
            flash("Falta removida.", "success")
        return redirect(url_for("admin.faltas"))

    rows = db.execute(
        """SELECT fa.*, f.nome_completo
             FROM faltas fa JOIN funcionarios f ON f.id = fa.funcionario_id
            ORDER BY fa.data DESC LIMIT 200"""
    ).fetchall()
    funcionarios = db.execute("SELECT id, nome_completo FROM funcionarios WHERE ativo = 1 ORDER BY nome_completo").fetchall()
    return render_template("admin/faltas.html", rows=rows, funcionarios=funcionarios)


# ----------------------------- Salários -----------------------------
@bp.route("/salarios", methods=["GET", "POST"])
@admin_required
def salarios():
    db = get_db()
    today = date.today()
    year = request.values.get("ano", default=today.year, type=int)
    month = request.values.get("mes", default=today.month, type=int)

    if request.method == "POST" and request.form.get("action") == "process_all":
        for f in db.execute("SELECT id FROM funcionarios WHERE ativo = 1").fetchall():
            persist_salary(f["id"], year, month)
        flash(f"Salários de {month:02d}/{year} processados.", "success")
        return redirect(url_for("admin.salarios", ano=year, mes=month))

    funcionarios = db.execute(
        "SELECT id, nome_completo, cargo, salario_hora FROM funcionarios WHERE ativo = 1 ORDER BY nome_completo"
    ).fetchall()
    rows = [{"func": f, "info": compute_salary(f["id"], year, month)} for f in funcionarios]
    total_liquido = sum(r["info"]["salario_liquido"] for r in rows)
    return render_template(
        "admin/salarios.html",
        rows=rows, year=year, month=month, total_liquido=round(total_liquido, 2),
    )


# ----------------------------- Estatísticas -----------------------------
@bp.route("/estatisticas")
@admin_required
def estatisticas():
    db = get_db()
    today = date.today()
    presencas_30d = []
    for i in range(29, -1, -1):
        day = today - timedelta(days=i)
        c = db.execute(
            "SELECT COUNT(DISTINCT funcionario_id) AS c FROM sessoes_trabalho WHERE data = ?",
            (day.isoformat(),),
        ).fetchone()["c"]
        presencas_30d.append({"data": day.isoformat(), "presencas": c})

    cargos_count = db.execute(
        "SELECT cargo, COUNT(*) AS c FROM funcionarios WHERE ativo = 1 GROUP BY cargo"
    ).fetchall()

    horas_por_func = db.execute(
        """SELECT f.nome_completo,
                  COALESCE(SUM(s.total_minutos),0) AS minutos
             FROM funcionarios f
             LEFT JOIN sessoes_trabalho s ON s.funcionario_id = f.id
                 AND CAST(strftime('%Y', s.data) AS INT) = ?
                 AND CAST(strftime('%m', s.data) AS INT) = ?
            WHERE f.ativo = 1
            GROUP BY f.id ORDER BY minutos DESC""",
        (today.year, today.month),
    ).fetchall()

    faltas_por_cargo = db.execute(
        """SELECT f.cargo, COUNT(*) AS c
             FROM faltas fa JOIN funcionarios f ON f.id = fa.funcionario_id
            WHERE CAST(strftime('%Y', fa.data) AS INT) = ?
            GROUP BY f.cargo""",
        (today.year,),
    ).fetchall()

    return render_template(
        "admin/estatisticas.html",
        presencas_30d=presencas_30d,
        cargos_count=cargos_count,
        horas_por_func=horas_por_func,
        faltas_por_cargo=faltas_por_cargo,
        format_minutes=format_minutes,
    )


# ----------------------------- Departamentos -----------------------------
@bp.route("/departamentos", methods=["GET", "POST"])
@admin_required
def departamentos():
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            try:
                db.execute(
                    "INSERT INTO departamentos (nome, descricao) VALUES (?, ?)",
                    (request.form["nome"].strip(), request.form.get("descricao", "")),
                )
                db.commit()
                flash("Departamento criado.", "success")
            except Exception as e:
                flash(f"Erro: {e}", "error")
        elif action == "delete":
            db.execute("DELETE FROM departamentos WHERE id = ?", (int(request.form["id"]),))
            db.commit()
            flash("Departamento removido.", "success")
        return redirect(url_for("admin.departamentos"))

    rows = db.execute(
        """SELECT d.*, COUNT(f.id) AS num_funcionarios
             FROM departamentos d
             LEFT JOIN funcionarios f ON f.departamento_id = d.id AND f.ativo = 1
            GROUP BY d.id ORDER BY d.nome"""
    ).fetchall()
    return render_template("admin/departamentos.html", rows=rows)


# ----------------------------- Pedidos de justificação -----------------------------
@bp.route("/justificacoes", methods=["GET", "POST"])
@admin_required
def justificacoes():
    db = get_db()
    if request.method == "POST":
        pid = int(request.form["id"])
        decisao = request.form.get("decisao")
        resposta = (request.form.get("resposta") or "").strip()
        ped = db.execute(
            """SELECT p.*, f.nome_completo FROM pedidos_falta p
                JOIN funcionarios f ON f.id = p.funcionario_id WHERE p.id = ?""",
            (pid,),
        ).fetchone()
        if not ped:
            abort(404)
        if decisao not in ("aprovado", "rejeitado"):
            flash("Decisão inválida.", "error")
        else:
            db.execute(
                """UPDATE pedidos_falta SET estado = ?, resposta_admin = ?, decided_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (decisao, resposta or None, pid),
            )
            # If approved, also create a registered absence
            if decisao == "aprovado":
                from datetime import date as _date, timedelta as _td
                def _to_date(v):
                    return v if isinstance(v, _date) else _date.fromisoformat(str(v))
                d1 = _to_date(ped["data_inicio"])
                d2 = _to_date(ped["data_fim"])
                cur = d1
                while cur <= d2:
                    db.execute(
                        """INSERT OR IGNORE INTO faltas
                           (funcionario_id, data, justificada, motivo)
                           VALUES (?, ?, 1, ?)""",
                        (ped["funcionario_id"], cur.isoformat(), ped["motivo"]),
                    )
                    cur += _td(days=1)
            db.commit()
            notify("funcionario", ped["funcionario_id"],
                   f"Justificação {decisao}",
                   f"O seu pedido de {ped['data_inicio']} foi {decisao}." + (f" Resposta: {resposta}" if resposta else ""),
                   "success" if decisao == "aprovado" else "error")
            flash(f"Pedido {decisao}.", "success")
        return redirect(url_for("admin.justificacoes"))

    rows = db.execute(
        """SELECT p.*, f.nome_completo, f.cargo
             FROM pedidos_falta p JOIN funcionarios f ON f.id = p.funcionario_id
            ORDER BY CASE p.estado WHEN 'pendente' THEN 0 ELSE 1 END, p.created_at DESC"""
    ).fetchall()
    return render_template("admin/justificacoes.html", rows=rows)


# ----------------------------- Pedidos de férias -----------------------------
@bp.route("/ferias", methods=["GET", "POST"])
@admin_required
def ferias_admin():
    db = get_db()
    if request.method == "POST":
        pid = int(request.form["id"])
        decisao = request.form.get("decisao")
        resposta = (request.form.get("resposta") or "").strip()
        ped = db.execute(
            """SELECT p.*, f.nome_completo FROM pedidos_ferias p
                JOIN funcionarios f ON f.id = p.funcionario_id WHERE p.id = ?""",
            (pid,),
        ).fetchone()
        if not ped:
            abort(404)
        if decisao not in ("aprovado", "rejeitado"):
            flash("Decisão inválida.", "error")
        else:
            db.execute(
                """UPDATE pedidos_ferias SET estado = ?, resposta_admin = ?, decided_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (decisao, resposta or None, pid),
            )
            db.commit()
            notify("funcionario", ped["funcionario_id"],
                   f"Férias {decisao}",
                   f"O seu pedido de {ped['dias']} dias ({ped['data_inicio']} a {ped['data_fim']}) foi {decisao}.",
                   "success" if decisao == "aprovado" else "error")
            flash(f"Pedido {decisao}.", "success")
        return redirect(url_for("admin.ferias_admin"))

    rows = db.execute(
        """SELECT p.*, f.nome_completo, f.cargo, f.dias_ferias_ano
             FROM pedidos_ferias p JOIN funcionarios f ON f.id = p.funcionario_id
            ORDER BY CASE p.estado WHEN 'pendente' THEN 0 ELSE 1 END, p.created_at DESC"""
    ).fetchall()
    funcionarios = db.execute(
        "SELECT id, nome_completo, dias_ferias_ano FROM funcionarios WHERE ativo = 1 ORDER BY nome_completo"
    ).fetchall()
    saldos = []
    for f in funcionarios:
        saldos.append({"func": f, "bal": balance(dict(f), date.today().year)})
    return render_template("admin/ferias.html", rows=rows, saldos=saldos)


# ----------------------------- Notificações (admin) -----------------------------
@bp.route("/notificacoes")
@admin_required
def notificacoes():
    rows = list_for("admin", None, limit=100)
    mark_all_read("admin", None)
    return render_template("admin/notificacoes.html", rows=rows)


# ----------------------------- Funcionário foto (admin upload) -----------------------------
@bp.route("/funcionarios/<int:fid>/foto", methods=["POST"])
@admin_required
def funcionarios_foto(fid: int):
    import base64, uuid, os as _os
    db = get_db()
    func = db.execute("SELECT id FROM funcionarios WHERE id = ?", (fid,)).fetchone()
    if not func:
        abort(404)
    data_url = request.form.get("foto_data") or ""
    if not data_url.startswith("data:image"):
        flash("Imagem inválida.", "error")
        return redirect(url_for("admin.funcionarios_edit", fid=fid))
    header, b64 = data_url.split(",", 1)
    ext = "png" if "png" in header else "jpg"
    name = f"avatar_{fid}_{uuid.uuid4().hex[:8]}.{ext}"
    path = _os.path.join(current_app.config["UPLOAD_DIR"], name)
    with open(path, "wb") as fh:
        fh.write(base64.b64decode(b64))
    db.execute("UPDATE funcionarios SET foto_perfil = ? WHERE id = ?", (name, fid))
    db.commit()
    flash("Foto atualizada.", "success")
    return redirect(url_for("admin.funcionarios_edit", fid=fid))


# ----------------------------- Uploads -----------------------------
@bp.route("/uploads/<path:filename>")
@admin_required
def uploads(filename):
    return send_from_directory(current_app.config["UPLOAD_DIR"], filename)
