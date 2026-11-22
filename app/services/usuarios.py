"""Alta y consulta de usuarios."""

import sqlite3
from dataclasses import dataclass

from app.auth import hash_password, verify_password
from app.clock import Clock, system_clock, to_iso

ROLES = ("admin", "agente")


class UsuarioError(ValueError):
    """Datos de usuario inválidos."""


class EmailDuplicadoError(UsuarioError):
    """Ya existe un usuario con ese email."""


@dataclass(frozen=True)
class Usuario:
    id: int
    email: str
    nombre: str
    rol: str
    activo: bool
    creado_en: str


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _from_row(row: sqlite3.Row) -> Usuario:
    return Usuario(
        id=row["id"],
        email=row["email"],
        nombre=row["nombre"],
        rol=row["rol"],
        activo=bool(row["activo"]),
        creado_en=row["creado_en"],
    )


def create_user(
    conn: sqlite3.Connection,
    *,
    email: str,
    nombre: str,
    password: str,
    rol: str = "agente",
    clock: Clock = system_clock,
) -> Usuario:
    email = normalize_email(email)
    nombre = nombre.strip()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise UsuarioError("El email no es válido.")
    if not nombre:
        raise UsuarioError("El nombre no puede estar vacío.")
    if rol not in ROLES:
        raise UsuarioError(f"Rol no válido: debe ser uno de {', '.join(ROLES)}.")
    password_hash = hash_password(password)
    try:
        cursor = conn.execute(
            "INSERT INTO usuarios (email, nombre, password_hash, rol, activo, creado_en) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (email, nombre, password_hash, rol, to_iso(clock())),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise EmailDuplicadoError(f"Ya existe un usuario con el email {email}.") from exc
    row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _from_row(row)


def get_user(conn: sqlite3.Connection, user_id: int) -> Usuario | None:
    row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (user_id,)).fetchone()
    return _from_row(row) if row else None


def listar_usuarios_activos(conn: sqlite3.Connection) -> list[Usuario]:
    filas = conn.execute("SELECT * FROM usuarios WHERE activo = 1 ORDER BY nombre, id").fetchall()
    return [_from_row(f) for f in filas]


def get_user_by_email(conn: sqlite3.Connection, email: str) -> Usuario | None:
    row = conn.execute(
        "SELECT * FROM usuarios WHERE email = ?", (normalize_email(email),)
    ).fetchone()
    return _from_row(row) if row else None


def check_credentials(conn: sqlite3.Connection, email: str, password: str) -> Usuario | None:
    """Devuelve el usuario activo si la contraseña es correcta; si no, None."""
    row = conn.execute(
        "SELECT * FROM usuarios WHERE email = ?", (normalize_email(email),)
    ).fetchone()
    if row is None or not row["activo"]:
        return None
    return _from_row(row) if verify_password(password, row["password_hash"]) else None
