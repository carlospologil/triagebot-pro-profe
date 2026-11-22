"""Alta, consulta y gestión de usuarios."""

import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from app.auth import hash_password, validate_password, verify_password
from app.clock import Clock, system_clock, to_iso
from app.services import auditoria

ROLES = ("admin", "agente")


class UsuarioError(ValueError):
    """Datos de usuario inválidos."""


class EmailDuplicadoError(UsuarioError):
    """Ya existe un usuario con ese email."""


class UsuarioNoEncontradoError(UsuarioError):
    """El usuario indicado no existe."""


class ProteccionError(UsuarioError):
    """La acción dejaría al equipo sin un administrador activo o es una autodesactivación."""


class PasswordActualIncorrectaError(UsuarioError):
    """La contraseña actual indicada no coincide."""


@dataclass(frozen=True)
class Usuario:
    id: int
    email: str
    nombre: str
    rol: str
    activo: bool
    creado_en: str
    debe_cambiar_password: bool = False


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
        debe_cambiar_password=bool(row["debe_cambiar_password"]),
    )


def create_user(
    conn: sqlite3.Connection,
    *,
    email: str,
    nombre: str,
    password: str,
    rol: str = "agente",
    clock: Clock = system_clock,
    actor_id: int | None = None,
    debe_cambiar_password: bool = False,
) -> Usuario:
    """Crea un usuario y lo registra en la auditoría a nombre de `actor_id` (None: sin sesión)."""
    email = normalize_email(email)
    nombre = nombre.strip()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise UsuarioError("El email no es válido.")
    if not nombre:
        raise UsuarioError("El nombre no puede estar vacío.")
    if rol not in ROLES:
        raise UsuarioError(f"Rol no válido: debe ser uno de {', '.join(ROLES)}.")
    password_hash = hash_password(password)
    ahora = to_iso(clock())
    try:
        cursor = conn.execute(
            "INSERT INTO usuarios "
            "(email, nombre, password_hash, rol, activo, creado_en, debe_cambiar_password) "
            "VALUES (?, ?, ?, ?, 1, ?, ?)",
            (email, nombre, password_hash, rol, ahora, int(debe_cambiar_password)),
        )
        auditoria.registrar(
            conn,
            auditoria.USUARIO_CREADO,
            ahora=ahora,
            usuario_id=actor_id,
            valor_nuevo=f"{email} ({rol})",
            detalle=None if actor_id is not None else "Alta sin sesión (línea de comandos)",
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


def listar_usuarios(conn: sqlite3.Connection) -> list[Usuario]:
    """Todos los usuarios, activos primero."""
    filas = conn.execute("SELECT * FROM usuarios ORDER BY activo DESC, nombre, id").fetchall()
    return [_from_row(f) for f in filas]


def generar_password_temporal() -> str:
    return secrets.token_urlsafe(12)


@contextmanager
def _transaccion(conn: sqlite3.Connection) -> Iterator[None]:
    """Transacción de escritura: serializa las comprobaciones y los cambios entre peticiones."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _cargar(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise UsuarioNoEncontradoError("El usuario no existe.")
    return row


def _hay_otro_admin_activo(conn: sqlite3.Connection, user_id: int) -> bool:
    fila = conn.execute(
        "SELECT 1 FROM usuarios WHERE rol = 'admin' AND activo = 1 AND id != ? LIMIT 1",
        (user_id,),
    ).fetchone()
    return fila is not None


def cambiar_rol(
    conn: sqlite3.Connection,
    user_id: int,
    rol: str,
    *,
    actor_id: int,
    clock: Clock = system_clock,
) -> Usuario:
    """Cambia el rol. No se puede quitar el rol de admin al último admin activo."""
    if rol not in ROLES:
        raise UsuarioError(f"Rol no válido: debe ser uno de {', '.join(ROLES)}.")
    with _transaccion(conn):
        row = _cargar(conn, user_id)
        if row["rol"] != rol:
            if (
                row["rol"] == "admin"
                and row["activo"]
                and not _hay_otro_admin_activo(conn, user_id)
            ):
                raise ProteccionError("No se puede quitar el rol al último administrador activo.")
            conn.execute("UPDATE usuarios SET rol = ? WHERE id = ?", (rol, user_id))
            auditoria.registrar(
                conn,
                auditoria.USUARIO_ROL_CAMBIADO,
                ahora=to_iso(clock()),
                usuario_id=actor_id,
                valor_anterior=row["rol"],
                valor_nuevo=rol,
                detalle=row["email"],
            )
    return _from_row(_cargar(conn, user_id))


def desactivar(
    conn: sqlite3.Connection, user_id: int, *, actor_id: int, clock: Clock = system_clock
) -> Usuario:
    """Desactiva al usuario (pierde el acceso al instante). Un admin no puede desactivarse."""
    with _transaccion(conn):
        row = _cargar(conn, user_id)
        if user_id == actor_id:
            raise ProteccionError("No puedes desactivar tu propia cuenta.")
        if row["activo"]:
            if row["rol"] == "admin" and not _hay_otro_admin_activo(conn, user_id):
                raise ProteccionError("No se puede desactivar al último administrador activo.")
            conn.execute("UPDATE usuarios SET activo = 0 WHERE id = ?", (user_id,))
            auditoria.registrar(
                conn,
                auditoria.USUARIO_DESACTIVADO,
                ahora=to_iso(clock()),
                usuario_id=actor_id,
                detalle=row["email"],
            )
    return _from_row(_cargar(conn, user_id))


def reactivar(
    conn: sqlite3.Connection, user_id: int, *, actor_id: int, clock: Clock = system_clock
) -> Usuario:
    with _transaccion(conn):
        row = _cargar(conn, user_id)
        if not row["activo"]:
            conn.execute(
                "UPDATE usuarios SET activo = 1, intentos_fallidos = 0, bloqueado_hasta = NULL "
                "WHERE id = ?",
                (user_id,),
            )
            auditoria.registrar(
                conn,
                auditoria.USUARIO_REACTIVADO,
                ahora=to_iso(clock()),
                usuario_id=actor_id,
                detalle=row["email"],
            )
    return _from_row(_cargar(conn, user_id))


def restablecer_password(
    conn: sqlite3.Connection, user_id: int, *, actor_id: int, clock: Clock = system_clock
) -> str:
    """Genera una contraseña temporal, obliga a cambiarla al entrar y la devuelve en claro.

    Es la única vez que se conoce: en la base de datos solo queda su hash.
    """
    temporal = generar_password_temporal()
    password_hash = hash_password(temporal)
    with _transaccion(conn):
        row = _cargar(conn, user_id)
        conn.execute(
            "UPDATE usuarios SET password_hash = ?, debe_cambiar_password = 1, "
            "intentos_fallidos = 0, bloqueado_hasta = NULL WHERE id = ?",
            (password_hash, user_id),
        )
        auditoria.registrar(
            conn,
            auditoria.PASSWORD_RESTABLECIDA,
            ahora=to_iso(clock()),
            usuario_id=actor_id,
            detalle=row["email"],
        )
    return temporal


def cambiar_password(
    conn: sqlite3.Connection,
    user_id: int,
    actual: str,
    nueva: str,
    *,
    clock: Clock = system_clock,
) -> None:
    """Cambia la contraseña del propio usuario exigiendo la actual."""
    validate_password(nueva)
    if nueva == actual:
        raise UsuarioError("La nueva contraseña debe ser distinta de la actual.")
    nuevo_hash = hash_password(nueva)
    with _transaccion(conn):
        row = _cargar(conn, user_id)
        if not verify_password(actual, row["password_hash"]):
            raise PasswordActualIncorrectaError("La contraseña actual no es correcta.")
        conn.execute(
            "UPDATE usuarios SET password_hash = ?, debe_cambiar_password = 0 WHERE id = ?",
            (nuevo_hash, user_id),
        )
        auditoria.registrar(
            conn, auditoria.PASSWORD_CAMBIADA, ahora=to_iso(clock()), usuario_id=user_id
        )


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
