"""Internal AJAX endpoints (admin face capture etc.)."""
from flask import Blueprint, request, jsonify

from ..services.auth_service import admin_required
from ..services.face_service import (
    compute_encoding_from_data_url,
    save_encoding,
    save_snapshot,
)
from ..db import get_db

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.post("/funcionarios/<int:fid>/face")
@admin_required
def add_face_sample(fid: int):
    payload = request.get_json(silent=True) or {}
    image = payload.get("image")
    if not image:
        return jsonify({"ok": False, "error": "Imagem em falta."}), 400

    db = get_db()
    func = db.execute("SELECT id FROM funcionarios WHERE id = ?", (fid,)).fetchone()
    if not func:
        return jsonify({"ok": False, "error": "Funcionário não encontrado."}), 404

    enc = compute_encoding_from_data_url(image)
    if enc is None:
        return jsonify({"ok": False, "error": "Nenhum rosto detectado na imagem. Tente novamente."}), 200

    snapshot = save_snapshot(image, prefix=f"face_{fid}")
    save_encoding(fid, enc)

    # Update foto_path to first sample if not set yet
    db.execute(
        "UPDATE funcionarios SET foto_path = COALESCE(foto_path, ?) WHERE id = ?",
        (snapshot, fid),
    )
    db.commit()

    count = db.execute(
        "SELECT COUNT(*) AS c FROM face_encodings WHERE funcionario_id = ?",
        (fid,),
    ).fetchone()["c"]
    return jsonify({"ok": True, "samples": count, "snapshot": snapshot})


@bp.post("/funcionarios/<int:fid>/face/clear")
@admin_required
def clear_face(fid: int):
    db = get_db()
    db.execute("DELETE FROM face_encodings WHERE funcionario_id = ?", (fid,))
    db.commit()
    return jsonify({"ok": True})
