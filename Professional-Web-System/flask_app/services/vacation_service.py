"""Vacation balance helpers."""
from __future__ import annotations

from datetime import date

from ..db import get_db


def days_used(funcionario_id: int, year: int) -> int:
    """Sum of approved vacation days within `year`."""
    db = get_db()
    row = db.execute(
        """SELECT COALESCE(SUM(dias), 0) AS d FROM pedidos_ferias
            WHERE funcionario_id = ?
              AND estado = 'aprovado'
              AND CAST(strftime('%Y', data_inicio) AS INT) = ?""",
        (funcionario_id, year),
    ).fetchone()
    return int(row["d"] or 0)


def balance(funcionario: dict, year: int | None = None) -> dict:
    year = year or date.today().year
    total = int(funcionario["dias_ferias_ano"] or 22)
    used = days_used(funcionario["id"], year)
    return {"total": total, "used": used, "remaining": max(0, total - used), "year": year}


def count_business_days(d1: date, d2: date) -> int:
    """Count days between d1 and d2 inclusive, excluding Sat/Sun."""
    if d2 < d1:
        return 0
    days = 0
    cur = d1
    while cur <= d2:
        if cur.weekday() < 5:
            days += 1
        cur = cur.fromordinal(cur.toordinal() + 1)
    return days
