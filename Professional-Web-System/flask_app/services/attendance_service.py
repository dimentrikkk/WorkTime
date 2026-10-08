"""Attendance / time tracking calculations."""
from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import Optional

from flask import current_app

from ..db import get_db


def _parse(ts: str) -> datetime:
    if isinstance(ts, datetime):
        return ts
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00").split("+")[0])


def open_session_for(funcionario_id: int) -> Optional[dict]:
    db = get_db()
    return db.execute(
        """SELECT * FROM sessoes_trabalho
           WHERE funcionario_id = ? AND hora_saida IS NULL
           ORDER BY hora_entrada DESC LIMIT 1""",
        (funcionario_id,),
    ).fetchone()


def register_punch(funcionario_id: int, foto_path: Optional[str] = None,
                   tipo: Optional[str] = None) -> dict:
    """Register entrada or saida.

    If `tipo` is provided ('entrada' or 'saida'), forces that operation and
    raises ValueError when the state doesn't match (e.g. saída without an open
    session, or entrada with a session already open). When `tipo` is None it
    auto-toggles based on the current open session.
    """
    db = get_db()
    now = datetime.now().replace(microsecond=0)
    today = now.date()
    existing = open_session_for(funcionario_id)

    if tipo == "entrada" or (tipo is None and existing is None):
        if existing is not None:
            raise ValueError("Já tem uma entrada em curso. Marque a saída primeiro.")
        atraso = _compute_late_minutes(funcionario_id, now)
        db.execute(
            """INSERT INTO sessoes_trabalho
               (funcionario_id, data, hora_entrada, hora_saida, total_minutos, atraso_minutos)
               VALUES (?, ?, ?, NULL, 0, ?)""",
            (funcionario_id, today.isoformat(), now.isoformat(sep=" "), atraso),
        )
        db.execute(
            "INSERT INTO registos_ponto (funcionario_id, tipo, timestamp, foto_path) VALUES (?, 'entrada', ?, ?)",
            (funcionario_id, now.isoformat(sep=" "), foto_path),
        )
        db.commit()
        return {"tipo": "entrada", "timestamp": now.isoformat(sep=" "), "atraso_minutos": atraso}

    if tipo == "saida" and existing is None:
        raise ValueError("Não existe entrada em aberto para registar saída.")

    entrada_dt = _parse(existing["hora_entrada"])
    total_minutos = max(0, int((now - entrada_dt).total_seconds() // 60))
    db.execute(
        "UPDATE sessoes_trabalho SET hora_saida = ?, total_minutos = ? WHERE id = ?",
        (now.isoformat(sep=" "), total_minutos, existing["id"]),
    )
    db.execute(
        "INSERT INTO registos_ponto (funcionario_id, tipo, timestamp, foto_path) VALUES (?, 'saida', ?, ?)",
        (funcionario_id, now.isoformat(sep=" "), foto_path),
    )
    db.commit()
    return {
        "tipo": "saida",
        "timestamp": now.isoformat(sep=" "),
        "total_minutos": total_minutos,
        "atraso_minutos": existing["atraso_minutos"],
    }


def _compute_late_minutes(funcionario_id: int, now: datetime) -> int:
    """How many minutes past the scheduled start time, if any."""
    db = get_db()
    weekday = now.weekday()  # Monday=0
    sched = db.execute(
        "SELECT hora_entrada FROM horarios WHERE funcionario_id = ? AND dia_semana = ?",
        (funcionario_id, weekday),
    ).fetchone()
    if not sched:
        return 0
    try:
        h, m = sched["hora_entrada"].split(":")
        scheduled = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    except Exception:
        return 0
    delta = (now - scheduled).total_seconds() / 60
    threshold = current_app.config.get("LATE_THRESHOLD_MINUTES", 5)
    if delta <= threshold:
        return 0
    return int(delta)


def total_minutes_in_month(funcionario_id: int, year: int, month: int) -> int:
    db = get_db()
    row = db.execute(
        """SELECT COALESCE(SUM(total_minutos), 0) AS m
             FROM sessoes_trabalho
            WHERE funcionario_id = ?
              AND CAST(strftime('%Y', data) AS INT) = ?
              AND CAST(strftime('%m', data) AS INT) = ?""",
        (funcionario_id, year, month),
    ).fetchone()
    return int(row["m"] or 0)


def total_late_in_month(funcionario_id: int, year: int, month: int) -> int:
    db = get_db()
    row = db.execute(
        """SELECT COALESCE(SUM(atraso_minutos), 0) AS m
             FROM sessoes_trabalho
            WHERE funcionario_id = ?
              AND CAST(strftime('%Y', data) AS INT) = ?
              AND CAST(strftime('%m', data) AS INT) = ?""",
        (funcionario_id, year, month),
    ).fetchone()
    return int(row["m"] or 0)


def absences_in_month(funcionario_id: int, year: int, month: int) -> int:
    db = get_db()
    row = db.execute(
        """SELECT COUNT(*) AS c FROM faltas
            WHERE funcionario_id = ?
              AND CAST(strftime('%Y', data) AS INT) = ?
              AND CAST(strftime('%m', data) AS INT) = ?
              AND justificada = 0""",
        (funcionario_id, year, month),
    ).fetchone()
    return int(row["c"] or 0)


def format_minutes(mins: int) -> str:
    h, m = divmod(int(mins or 0), 60)
    return f"{h:02d}h{m:02d}"
