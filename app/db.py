"""Acceso a SQLite (librería estándar) y sistema de migraciones versionado."""

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Request


def connect(database_path: str) -> sqlite3.Connection:
    # FastAPI puede ejecutar la dependencia get_db y el endpoint síncrono en hilos distintos
    # del threadpool; la conexión es de una sola petición, así que no se usa a la vez.
    conn = sqlite3.connect(database_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    """Dependencia de FastAPI: una conexión por petición."""
    conn = connect(request.app.state.settings.database_path)
    try:
        yield conn
    finally:
        conn.close()


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="esquema_inicial",
        statements=(
            """
            CREATE TABLE usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                nombre TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                rol TEXT NOT NULL DEFAULT 'agente' CHECK (rol IN ('admin', 'agente')),
                activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
                creado_en TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asunto TEXT NOT NULL,
                descripcion TEXT NOT NULL,
                solicitante_nombre TEXT NOT NULL,
                solicitante_email TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'nuevo',
                prioridad TEXT NOT NULL DEFAULT 'media',
                categoria TEXT,
                resumen_ia TEXT,
                asignado_a INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
                fecha_limite TEXT,
                creado_en TEXT NOT NULL,
                actualizado_en TEXT NOT NULL,
                resuelto_en TEXT
            )
            """,
            "CREATE INDEX idx_tickets_estado ON tickets(estado)",
            "CREATE INDEX idx_tickets_prioridad ON tickets(prioridad)",
            "CREATE INDEX idx_tickets_categoria ON tickets(categoria)",
            "CREATE INDEX idx_tickets_asignado_a ON tickets(asignado_a)",
            "CREATE INDEX idx_tickets_fecha_limite ON tickets(fecha_limite)",
            "CREATE INDEX idx_tickets_creado_en ON tickets(creado_en)",
            """
            CREATE TABLE comentarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                autor_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
                cuerpo TEXT NOT NULL,
                interno INTEGER NOT NULL DEFAULT 0 CHECK (interno IN (0, 1)),
                creado_en TEXT NOT NULL
            )
            """,
            "CREATE INDEX idx_comentarios_ticket_id ON comentarios(ticket_id)",
            "CREATE INDEX idx_comentarios_autor_id ON comentarios(autor_id)",
            """
            CREATE TABLE auditoria (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL,
                usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
                accion TEXT NOT NULL,
                detalle TEXT,
                creado_en TEXT NOT NULL
            )
            """,
            "CREATE INDEX idx_auditoria_ticket_id ON auditoria(ticket_id)",
            "CREATE INDEX idx_auditoria_usuario_id ON auditoria(usuario_id)",
            "CREATE INDEX idx_auditoria_creado_en ON auditoria(creado_en)",
        ),
    ),
    Migration(
        version=2,
        name="bloqueo_de_acceso",
        statements=(
            "ALTER TABLE usuarios ADD COLUMN intentos_fallidos INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE usuarios ADD COLUMN bloqueado_hasta TEXT",
        ),
    ),
    Migration(
        version=3,
        name="ciclo_de_vida_del_ticket",
        statements=(
            "UPDATE tickets SET estado = 'en_curso' WHERE estado = 'en_progreso'",
            "UPDATE tickets SET estado = 'esperando_cliente' WHERE estado = 'pendiente'",
            "ALTER TABLE tickets ADD COLUMN corregido_por_persona INTEGER NOT NULL DEFAULT 0 "
            "CHECK (corregido_por_persona IN (0, 1))",
        ),
    ),
)


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) AS version FROM schema_version").fetchone()
    return row["version"] or 0


def migrate(conn: sqlite3.Connection, migrations: tuple[Migration, ...] = MIGRATIONS) -> list[int]:
    """Aplica en orden las migraciones pendientes y devuelve sus versiones.

    Cada migración se ejecuta en su propia transacción exclusiva, de modo que dos
    procesos que arranquen a la vez no la apliquen dos veces.
    """
    versions = [m.version for m in migrations]
    if versions != sorted(set(versions)):
        raise ValueError("Las migraciones deben tener versiones únicas y ascendentes")

    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "version INTEGER PRIMARY KEY, nombre TEXT NOT NULL, aplicada_en TEXT NOT NULL)"
    )
    conn.commit()

    applied: list[int] = []
    for migration in migrations:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if migration.version <= current_version(conn):
                conn.rollback()
                continue
            for statement in migration.statements:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_version (version, nombre, aplicada_en) "
                "VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))",
                (migration.version, migration.name),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        applied.append(migration.version)
    return applied


def init_db(database_path: str) -> list[int]:
    conn = connect(database_path)
    try:
        return migrate(conn)
    finally:
        conn.close()
