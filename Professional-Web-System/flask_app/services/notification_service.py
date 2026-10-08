"""Notifications service: in-app feed for employees and admins."""
from __future__ import annotations

from typing import Optional

from ..db import get_db


def notify(destinatario_tipo: str, destinatario_id: Optional[int],
           titulo: str, mensagem: str, tipo: str = "info") -> None:
    """Create a notification for a specific employee or all admins.

    destinatario_tipo: 'funcionario' or 'admin'
    destinatario_id: funcionario id, or None for "all admins"
    tipo: info | success | warn | error
    """
    db = get_db()
    db.execute(
        """INSERT INTO notificacoes
           (destinatario_tipo, destinatario_id, titulo, mensagem, tipo)
           VALUES (?, ?, ?, ?, ?)""",
        (destinatario_tipo, destinatario_id, titulo, mensagem, tipo),
    )
    db.commit()


def list_for(destinatario_tipo: str, destinatario_id: Optional[int],
             limit: int = 25, only_unread: bool = False):
    db = get_db()
    sql = """SELECT * FROM notificacoes
             WHERE destinatario_tipo = ?
               AND (destinatario_id = ? OR (? IS NULL AND destinatario_id IS NULL))"""
    args = [destinatario_tipo, destinatario_id, destinatario_id]
    if only_unread:
        sql += " AND lida = 0"
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    return db.execute(sql, args).fetchall()


def unread_count(destinatario_tipo: str, destinatario_id: Optional[int]) -> int:
    db = get_db()
    row = db.execute(
        """SELECT COUNT(*) AS c FROM notificacoes
           WHERE destinatario_tipo = ?
             AND (destinatario_id = ? OR (? IS NULL AND destinatario_id IS NULL))
             AND lida = 0""",
        (destinatario_tipo, destinatario_id, destinatario_id),
    ).fetchone()
    return int(row["c"] or 0)


def mark_all_read(destinatario_tipo: str, destinatario_id: Optional[int]) -> None:
    db = get_db()
    db.execute(
        """UPDATE notificacoes SET lida = 1
           WHERE destinatario_tipo = ?
             AND (destinatario_id = ? OR (? IS NULL AND destinatario_id IS NULL))""",
        (destinatario_tipo, destinatario_id, destinatario_id),
    )
    db.commit()
