"""Kiosk (tablet) interface routes."""
from datetime import datetime

from flask import Blueprint, render_template, request, jsonify

from ..db import get_db
from ..services.face_service import identify, save_snapshot
from ..services.attendance_service import register_punch, format_minutes
from ..services.notification_service import notify

bp = Blueprint("kiosk", __name__, url_prefix="/kiosk")


@bp.route("/")
def index():
    return render_template("kiosk/index.html")


@bp.post("/recognize")
def recognize():
    payload = request.get_json(silent=True) or {}
    image = payload.get("image")
    tipo = payload.get("tipo")
    if tipo not in (None, "entrada", "saida"):
        return jsonify({"ok": False, "error": "Tipo inválido."}), 400
    if not image:
        return jsonify({"ok": False, "error": "Sem imagem."}), 400

    fid, dist = identify(image)
    if fid is None:
        return jsonify({
            "ok": False,
            "error": "Rosto não reconhecido." if dist is not None else "Nenhum rosto detectado.",
        }), 200

    db = get_db()
    func = db.execute(
        "SELECT id, nome_completo, cargo FROM funcionarios WHERE id = ? AND ativo = 1",
        (fid,),
    ).fetchone()
    if not func:
        return jsonify({"ok": False, "error": "Funcionário inactivo."}), 200

    snapshot = save_snapshot(image, prefix=f"punch_{fid}")
    try:
        result = register_punch(fid, foto_path=snapshot, tipo=tipo)
    except ValueError as e:
        return jsonify({
            "ok": False,
            "error": str(e),
            "funcionario": {"id": func["id"], "nome": func["nome_completo"], "cargo": func["cargo"]},
        }), 200

    # Push in-app notification to the employee with summary
    hora = datetime.fromisoformat(result["timestamp"]).strftime("%H:%M")
    if result["tipo"] == "entrada":
        atraso = result.get("atraso_minutos") or 0
        msg = f"Entrada registada às {hora}."
        if atraso:
            msg += f" Atraso de {atraso} minutos."
        notify("funcionario", fid, "Entrada registada", msg, "success" if not atraso else "warn")
    else:
        # Compute today's earnings
        salario_hora = db.execute(
            "SELECT salario_hora FROM funcionarios WHERE id = ?", (fid,)
        ).fetchone()["salario_hora"] or 0
        ganho = (result.get("total_minutos") or 0) / 60 * salario_hora
        msg = (f"Saída registada às {hora}. "
               f"Sessão: {format_minutes(result.get('total_minutos') or 0)}. "
               f"Ganhou hoje aprox. {ganho:.2f} €.")
        notify("funcionario", fid, "Saída registada", msg, "success")
    return jsonify({
        "ok": True,
        "funcionario": {
            "id": func["id"],
            "nome": func["nome_completo"],
            "cargo": func["cargo"],
        },
        "tipo": result["tipo"],
        "timestamp": result["timestamp"],
        "total_minutos": result.get("total_minutos"),
        "total_formatado": format_minutes(result.get("total_minutos") or 0),
        "atraso_minutos": result.get("atraso_minutos", 0),
        "distance": dist,
    })
