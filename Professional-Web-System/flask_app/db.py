"""SQLite database helpers and schema bootstrap."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from flask import current_app, g

import bcrypt


SCHEMA = """
CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS departamentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    descricao TEXT
);

CREATE TABLE IF NOT EXISTS funcionarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome_completo TEXT NOT NULL,
    idade INTEGER,
    email TEXT NOT NULL UNIQUE,
    telefone TEXT,
    nif TEXT,
    data_nascimento DATE,
    data_admissao DATE,
    tipo_contrato TEXT,
    morada TEXT,
    cidade TEXT,
    codigo_postal TEXT,
    cargo TEXT NOT NULL CHECK (cargo IN ('armazem','camionista','vendedor','secretaria')),
    departamento_id INTEGER REFERENCES departamentos(id) ON DELETE SET NULL,
    salario_hora REAL NOT NULL DEFAULT 0,
    password_hash TEXT NOT NULL,
    foto_path TEXT,
    notas TEXT,
    ativo INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS face_encodings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    funcionario_id INTEGER NOT NULL REFERENCES funcionarios(id) ON DELETE CASCADE,
    encoding BLOB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS horarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    funcionario_id INTEGER NOT NULL REFERENCES funcionarios(id) ON DELETE CASCADE,
    dia_semana INTEGER NOT NULL CHECK (dia_semana BETWEEN 0 AND 6),
    hora_entrada TEXT NOT NULL,
    hora_saida TEXT NOT NULL,
    UNIQUE(funcionario_id, dia_semana)
);

CREATE TABLE IF NOT EXISTS registos_ponto (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    funcionario_id INTEGER NOT NULL REFERENCES funcionarios(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL CHECK (tipo IN ('entrada','saida')),
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    foto_path TEXT
);

CREATE TABLE IF NOT EXISTS sessoes_trabalho (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    funcionario_id INTEGER NOT NULL REFERENCES funcionarios(id) ON DELETE CASCADE,
    data DATE NOT NULL,
    hora_entrada TIMESTAMP NOT NULL,
    hora_saida TIMESTAMP,
    total_minutos INTEGER DEFAULT 0,
    atraso_minutos INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS faltas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    funcionario_id INTEGER NOT NULL REFERENCES funcionarios(id) ON DELETE CASCADE,
    data DATE NOT NULL,
    justificada INTEGER NOT NULL DEFAULT 0,
    motivo TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(funcionario_id, data)
);

CREATE TABLE IF NOT EXISTS salarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    funcionario_id INTEGER NOT NULL REFERENCES funcionarios(id) ON DELETE CASCADE,
    mes INTEGER NOT NULL,
    ano INTEGER NOT NULL,
    total_horas REAL NOT NULL DEFAULT 0,
    salario_bruto REAL NOT NULL DEFAULT 0,
    descontos REAL NOT NULL DEFAULT 0,
    salario_liquido REAL NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(funcionario_id, mes, ano)
);

CREATE TABLE IF NOT EXISTS notificacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    destinatario_tipo TEXT NOT NULL CHECK (destinatario_tipo IN ('funcionario','admin')),
    destinatario_id INTEGER,
    titulo TEXT NOT NULL,
    mensagem TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'info',
    lida INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pedidos_falta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    funcionario_id INTEGER NOT NULL REFERENCES funcionarios(id) ON DELETE CASCADE,
    data_inicio DATE NOT NULL,
    data_fim DATE NOT NULL,
    motivo TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendente' CHECK (estado IN ('pendente','aprovado','rejeitado')),
    resposta_admin TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    decided_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pedidos_ferias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    funcionario_id INTEGER NOT NULL REFERENCES funcionarios(id) ON DELETE CASCADE,
    data_inicio DATE NOT NULL,
    data_fim DATE NOT NULL,
    dias INTEGER NOT NULL,
    motivo TEXT,
    estado TEXT NOT NULL DEFAULT 'pendente' CHECK (estado IN ('pendente','aprovado','rejeitado')),
    resposta_admin TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    decided_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    success INTEGER NOT NULL DEFAULT 0,
    ip TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_registos_func_time ON registos_ponto(funcionario_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_sessoes_func_data ON sessoes_trabalho(funcionario_id, data);
CREATE INDEX IF NOT EXISTS idx_notif_dest ON notificacoes(destinatario_tipo, destinatario_id, lida);
CREATE INDEX IF NOT EXISTS idx_login_email_time ON login_attempts(email, created_at);
"""


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(
            current_app.config["DATABASE_PATH"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def db_cursor() -> Iterator[sqlite3.Cursor]:
    db = get_db()
    cur = db.cursor()
    try:
        yield cur
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cur.close()


def init_db() -> None:
    db = sqlite3.connect(current_app.config["DATABASE_PATH"])
    db.executescript(SCHEMA)
    # Lightweight migrations for older databases
    cur = db.cursor()
    cur.execute("PRAGMA table_info(funcionarios)")
    existing_cols = {row[1] for row in cur.fetchall()}
    extra_cols = [
        ("telefone", "TEXT"),
        ("nif", "TEXT"),
        ("data_nascimento", "DATE"),
        ("data_admissao", "DATE"),
        ("tipo_contrato", "TEXT"),
        ("codigo_postal", "TEXT"),
        ("notas", "TEXT"),
        ("foto_perfil", "TEXT"),
        ("dias_ferias_ano", "INTEGER DEFAULT 22"),
    ]
    for col, ddl in extra_cols:
        if col not in existing_cols:
            cur.execute(f"ALTER TABLE funcionarios ADD COLUMN {col} {ddl}")
    db.commit()
    db.close()


def seed_initial_data() -> None:
    """Create default departments and a default admin if missing."""
    db = sqlite3.connect(current_app.config["DATABASE_PATH"])
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    # Default departments
    default_depts = [
        ("Armazém", "Gestão e operações de armazém"),
        ("Distribuição", "Camionistas e logística de entrega"),
        ("Comercial", "Equipa de vendedores"),
        ("Administrativo", "Secretárias e back-office"),
    ]
    for nome, desc in default_depts:
        cur.execute(
            "INSERT OR IGNORE INTO departamentos (nome, descricao) VALUES (?, ?)",
            (nome, desc),
        )

    # Default admin
    cur.execute("SELECT COUNT(*) AS c FROM admins")
    if cur.fetchone()["c"] == 0:
        from .config import Config
        pw_hash = bcrypt.hashpw(
            Config.DEFAULT_ADMIN_PASSWORD.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("utf-8")
        cur.execute(
            "INSERT INTO admins (nome, email, password_hash) VALUES (?, ?, ?)",
            (Config.DEFAULT_ADMIN_NAME, Config.DEFAULT_ADMIN_EMAIL, pw_hash),
        )

    db.commit()
    db.close()
