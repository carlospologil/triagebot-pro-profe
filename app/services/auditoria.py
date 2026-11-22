"""Registro inmutable de quién hizo qué y cuándo.

`registrar` no hace commit: el registro viaja en la misma transacción que el cambio auditado,
de modo que o se guardan los dos o ninguno. Solo hay funciones de alta y de lectura.
"""

import math
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

TICKET_CREADO = "ticket_creado"
TICKET_CLASIFICADO = "ticket_clasificado"
TICKET_RECLASIFICADO = "ticket_reclasificado"
ESTADO_CAMBIADO = "estado_cambiado"
PRIORIDAD_CAMBIADA = "prioridad_cambiada"
CATEGORIA_CAMBIADA = "categoria_cambiada"
ASIGNACION_CAMBIADA = "asignacion_cambiada"
LOGIN_CORRECTO = "login_correcto"
LOGIN_FALLIDO = "login_fallido"
USUARIO_CREADO = "usuario_creado"
USUARIO_ROL_CAMBIADO = "usuario_rol_cambiado"
USUARIO_DESACTIVADO = "usuario_desactivado"
USUARIO_REACTIVADO = "usuario_reactivado"
PASSWORD_RESTABLECIDA = "password_restablecida"
PASSWORD_CAMBIADA = "password_cambiada"

ETIQUETAS_ACCION = {
    TICKET_CREADO: "Ticket creado",
    TICKET_CLASIFICADO: "Clasificación automática",
    TICKET_RECLASIFICADO: "Reclasificación",
    ESTADO_CAMBIADO: "Cambio de estado",
    PRIORIDAD_CAMBIADA: "Cambio de prioridad",
    CATEGORIA_CAMBIADA: "Cambio de categoría",
    ASIGNACION_CAMBIADA: "Cambio de asignación",
    LOGIN_CORRECTO: "Inicio de sesión",
    LOGIN_FALLIDO: "Inicio de sesión fallido",
    USUARIO_CREADO: "Usuario creado",
    USUARIO_ROL_CAMBIADO: "Cambio de rol de usuario",
    USUARIO_DESACTIVADO: "Usuario desactivado",
    USUARIO_REACTIVADO: "Usuario reactivado",
    PASSWORD_RESTABLECIDA: "Contraseña restablecida",
    PASSWORD_CAMBIADA: "Contraseña cambiada",
}

TAMANO_PAGINA = 50
MAX_EMAIL_REGISTRADO = 254
MAX_ENTERO_SQLITE = 2**63 - 1


class FiltroInvalidoError(ValueError):
    """Un filtro del listado de auditoría no es válido."""


@dataclass(frozen=True)
class Registro:
    id: int
    ticket_id: int | None
    usuario_id: int | None
    usuario_email: str | None
    accion: str
    valor_anterior: str | None
    valor_nuevo: str | None
    detalle: str | None
    creado_en: str


@dataclass(frozen=True)
class PaginaAuditoria:
    items: list[Registro]
    total: int
    page: int
    page_size: int
    paginas: int


def registrar(
    conn: sqlite3.Connection,
    accion: str,
    *,
    ahora: str,
    usuario_id: int | None = None,
    usuario_email: str | None = None,
    ticket_id: int | None = None,
    valor_anterior: object = None,
    valor_nuevo: object = None,
    detalle: str | None = None,
) -> None:
    """Añade un registro (sin commit). El email del usuario se guarda como copia de su identidad."""
    if usuario_id is not None and usuario_email is None:
        fila = conn.execute("SELECT email FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        usuario_email = fila["email"] if fila else None
    conn.execute(
        "INSERT INTO auditoria (ticket_id, usuario_id, usuario_email, accion, valor_anterior, "
        "valor_nuevo, detalle, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            ticket_id,
            usuario_id,
            usuario_email,
            accion,
            None if valor_anterior is None else str(valor_anterior),
            None if valor_nuevo is None else str(valor_nuevo),
            detalle,
            ahora,
        ),
    )


def _a_registro(row: sqlite3.Row) -> Registro:
    return Registro(
        id=row["id"],
        ticket_id=row["ticket_id"],
        usuario_id=row["usuario_id"],
        usuario_email=row["usuario_email"],
        accion=row["accion"],
        valor_anterior=row["valor_anterior"],
        valor_nuevo=row["valor_nuevo"],
        detalle=row["detalle"],
        creado_en=row["creado_en"],
    )


def linea_de_tiempo(conn: sqlite3.Connection, ticket_id: int) -> list[Registro]:
    """Registros del ticket, del más antiguo al más reciente."""
    filas = conn.execute(
        "SELECT * FROM auditoria WHERE ticket_id = ? ORDER BY id", (ticket_id,)
    ).fetchall()
    return [_a_registro(f) for f in filas]


def _parsear_fecha(texto: str, nombre: str) -> date:
    try:
        return date.fromisoformat(texto)
    except ValueError:
        raise FiltroInvalidoError(f"La fecha «{nombre}» no es válida.") from None


def listar(
    conn: sqlite3.Connection,
    *,
    page: int = 1,
    page_size: int = TAMANO_PAGINA,
    usuario: str | None = None,
    accion: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
) -> PaginaAuditoria:
    """Registros más recientes primero.

    `usuario` es un id o un email; `desde` y `hasta` son fechas `AAAA-MM-DD` (UTC) y ambas
    se incluyen. Lanza FiltroInvalidoError si una fecha no es válida o el rango está invertido.
    """
    condiciones: list[str] = []
    parametros: list[object] = []

    usuario = (usuario or "").strip()
    if usuario:
        if usuario.isascii() and usuario.isdigit():
            usuario_id = int(usuario)
            if usuario_id > MAX_ENTERO_SQLITE:
                raise FiltroInvalidoError("El usuario indicado no es válido.")
            condiciones.append("usuario_id = ?")
            parametros.append(usuario_id)
        else:
            condiciones.append("usuario_email = ?")
            parametros.append(usuario.lower())

    accion = (accion or "").strip()
    if accion:
        condiciones.append("accion = ?")
        parametros.append(accion)

    fecha_desde = _parsear_fecha(desde.strip(), "desde") if desde and desde.strip() else None
    fecha_hasta = _parsear_fecha(hasta.strip(), "hasta") if hasta and hasta.strip() else None
    if fecha_desde and fecha_hasta and fecha_desde > fecha_hasta:
        raise FiltroInvalidoError("La fecha «desde» no puede ser posterior a «hasta».")
    if fecha_desde:
        condiciones.append("creado_en >= ?")
        parametros.append(fecha_desde.isoformat() + "T00:00:00Z")
    if fecha_hasta:
        condiciones.append("creado_en < ?")
        parametros.append((fecha_hasta + timedelta(days=1)).isoformat() + "T00:00:00Z")

    where = f" WHERE {' AND '.join(condiciones)}" if condiciones else ""
    total = conn.execute(f"SELECT COUNT(*) FROM auditoria{where}", parametros).fetchone()[0]
    paginas = math.ceil(total / page_size)
    page = max(1, min(page, paginas))
    filas = conn.execute(
        f"SELECT * FROM auditoria{where} ORDER BY id DESC LIMIT ? OFFSET ?",
        [*parametros, page_size, (page - 1) * page_size],
    ).fetchall()
    return PaginaAuditoria(
        items=[_a_registro(f) for f in filas],
        total=total,
        page=page,
        page_size=page_size,
        paginas=paginas,
    )
