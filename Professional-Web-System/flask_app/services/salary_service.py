"""Salary calculations."""
from __future__ import annotations

from datetime import date

from flask import current_app

from ..db import get_db
from .attendance_service import (
    total_minutes_in_month,
    total_late_in_month,
    absences_in_month,
)


def compute_salary(funcionario_id: int, year: int, month: int) -> dict:
    """Compute salary for a given month, returning a breakdown dict."""
    db = get_db()
    func = db.execute(
        "SELECT salario_hora FROM funcionarios WHERE id = ?",
        (funcionario_id,),
    ).fetchone()
    if not func:
        return {}
    rate = float(func["salario_hora"] or 0)

    minutos = total_minutes_in_month(funcionario_id, year, month)
    horas = minutos / 60.0
    bruto = horas * rate

    atraso_min = total_late_in_month(funcionario_id, year, month)
    desconto_atrasos = (atraso_min / 60.0) * rate

    faltas = absences_in_month(funcionario_id, year, month)
    horas_falta = current_app.config.get("HOURS_PER_FALTA", 8.0)
    desconto_faltas = faltas * horas_falta * rate

    descontos = desconto_atrasos + desconto_faltas
    liquido = max(0.0, bruto - descontos)

    return {
        "ano": year,
        "mes": month,
        "salario_hora": rate,
        "total_horas": round(horas, 2),
        "salario_bruto": round(bruto, 2),
        "atraso_minutos": atraso_min,
        "desconto_atrasos": round(desconto_atrasos, 2),
        "faltas": faltas,
        "desconto_faltas": round(desconto_faltas, 2),
        "descontos": round(descontos, 2),
        "salario_liquido": round(liquido, 2),
    }


def persist_salary(funcionario_id: int, year: int, month: int) -> dict:
    """Compute and store salary for the month."""
    info = compute_salary(funcionario_id, year, month)
    if not info:
        return {}
    db = get_db()
    db.execute(
        """INSERT INTO salarios (funcionario_id, mes, ano, total_horas, salario_bruto, descontos, salario_liquido)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(funcionario_id, mes, ano) DO UPDATE SET
               total_horas = excluded.total_horas,
               salario_bruto = excluded.salario_bruto,
               descontos = excluded.descontos,
               salario_liquido = excluded.salario_liquido,
               created_at = CURRENT_TIMESTAMP""",
        (funcionario_id, month, year, info["total_horas"], info["salario_bruto"], info["descontos"], info["salario_liquido"]),
    )
    db.commit()
    return info
