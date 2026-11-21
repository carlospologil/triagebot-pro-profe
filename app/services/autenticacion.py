"""Inicio de sesión con bloqueo temporal tras intentos fallidos seguidos."""

import sqlite3
from datetime import datetime, timedelta
from functools import lru_cache

from app.auth import hash_password, verify_password
from app.clock import Clock, to_iso
from app.services.usuarios import Usuario, _from_row, normalize_email

MAX_INTENTOS_FALLIDOS = 5
DURACION_BLOQUEO = timedelta(minutes=15)


@lru_cache(maxsize=1)
def _hash_señuelo() -> str:
    return hash_password("contraseña-señuelo")


def authenticate(
    conn: sqlite3.Connection, email: str, password: str, clock: Clock
) -> Usuario | None:
    """Devuelve el usuario si las credenciales son válidas y no está bloqueado.

    Para que no se pueda deducir qué emails existen, un email desconocido, un usuario
    inactivo o bloqueado y una contraseña errónea responden igual (None).

    La lectura, la verificación y la actualización del contador ocurren dentro de una
    transacción de escritura: los intentos simultáneos se serializan, de modo que no se
    pueden superar los 5 intentos ni evadir un bloqueo con un acierto concurrente.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        usuario = _autenticar(conn, email, password, clock())
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return usuario


def _autenticar(
    conn: sqlite3.Connection, email: str, password: str, momento: datetime
) -> Usuario | None:
    ahora = to_iso(momento)
    row = conn.execute(
        "SELECT * FROM usuarios WHERE email = ?", (normalize_email(email),)
    ).fetchone()

    if row is None or not row["activo"]:
        verify_password(password, _hash_señuelo())
        return None

    if row["bloqueado_hasta"] and row["bloqueado_hasta"] > ahora:
        verify_password(password, _hash_señuelo())
        return None

    if not verify_password(password, row["password_hash"]):
        # Un único UPDATE atómico: al llegar al máximo se bloquea y se reinicia el contador.
        conn.execute(
            "UPDATE usuarios SET "
            "intentos_fallidos = CASE WHEN intentos_fallidos + 1 >= ? "
            "THEN 0 ELSE intentos_fallidos + 1 END, "
            "bloqueado_hasta = CASE WHEN intentos_fallidos + 1 >= ? THEN ? "
            "ELSE bloqueado_hasta END "
            "WHERE id = ?",
            (
                MAX_INTENTOS_FALLIDOS,
                MAX_INTENTOS_FALLIDOS,
                to_iso(momento + DURACION_BLOQUEO),
                row["id"],
            ),
        )
        return None

    conn.execute(
        "UPDATE usuarios SET intentos_fallidos = 0, bloqueado_hasta = NULL WHERE id = ?",
        (row["id"],),
    )
    return _from_row(row)


def get_active_user(conn: sqlite3.Connection, user_id: int) -> Usuario | None:
    row = conn.execute("SELECT * FROM usuarios WHERE id = ? AND activo = 1", (user_id,)).fetchone()
    return _from_row(row) if row else None
