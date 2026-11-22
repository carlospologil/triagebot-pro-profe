"""Alta, consulta y actualización de tickets."""

import logging
import math
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.clock import Clock, system_clock, to_iso
from app.schemas import ESTADOS_FINALES, PaginaTickets, TicketCrear, TicketSalida
from app.services import clasificador

logger = logging.getLogger(__name__)

CAMPOS_EDITABLES = ("estado", "prioridad", "categoria", "asignado_a")
TAMANO_PAGINA_BANDEJA = 25
SIN_ASIGNAR = "sin_asignar"


@dataclass(frozen=True)
class FilaBandeja:
    id: int
    asunto: str
    solicitante_nombre: str
    categoria: str | None
    prioridad: str
    estado: str
    asignado_a: int | None
    asignado_nombre: str | None
    creado_en: str


@dataclass(frozen=True)
class PaginaBandeja:
    items: list[FilaBandeja]
    total: int
    page: int
    page_size: int
    paginas: int


class TicketNoEncontradoError(LookupError):
    """No existe el ticket pedido."""


class AsignadoInvalidoError(ValueError):
    """El usuario al que se asigna el ticket no existe o está desactivado."""


def _a_salida(row: sqlite3.Row) -> TicketSalida:
    return TicketSalida(
        id=row["id"],
        asunto=row["asunto"],
        texto=row["descripcion"],
        email_cliente=row["solicitante_email"],
        nombre_cliente=row["solicitante_nombre"],
        estado=row["estado"],
        prioridad=row["prioridad"],
        categoria=row["categoria"],
        resumen_ia=row["resumen_ia"],
        asignado_a=row["asignado_a"],
        fecha_limite=row["fecha_limite"],
        creado_en=row["creado_en"],
        actualizado_en=row["actualizado_en"],
        resuelto_en=row["resuelto_en"],
    )


def crear_ticket(
    conn: sqlite3.Connection, datos: TicketCrear, clock: Clock = system_clock
) -> TicketSalida:
    ahora = to_iso(clock())
    cursor = conn.execute(
        "INSERT INTO tickets (asunto, descripcion, solicitante_nombre, solicitante_email, "
        "estado, prioridad, creado_en, actualizado_en) VALUES (?, ?, ?, ?, 'nuevo', 'media', ?, ?)",
        (
            datos.asunto,
            datos.texto,
            datos.nombre_cliente or datos.email_cliente,
            datos.email_cliente,
            ahora,
            ahora,
        ),
    )
    conn.commit()
    return obtener_ticket(conn, cursor.lastrowid)


def clasificar_ticket(
    conn: sqlite3.Connection,
    ticket_id: int,
    cliente: Any | None,
    clock: Clock = system_clock,
    *,
    marcar_sin_clasificar: bool = False,
) -> TicketSalida:
    """Clasifica el ticket con el LLM y guarda categoría, prioridad y justificación.

    Si la IA falla el error se registra en el log. Con `marcar_sin_clasificar` el ticket queda
    como `sin_clasificar` (alta de ticket); si no, se relanza ClasificacionError y el ticket
    no se toca (reclasificación, para no pisar una clasificación previa por un fallo puntual).
    """
    ticket = obtener_ticket(conn, ticket_id)
    try:
        resultado = clasificador.clasificar(cliente, ticket.asunto, ticket.texto)
    except clasificador.ClasificacionError as exc:
        logger.error("No se pudo clasificar el ticket %s: %s", ticket_id, exc)
        if not marcar_sin_clasificar:
            raise
        cambios = {"categoria": clasificador.CATEGORIA_SIN_CLASIFICAR}
    else:
        cambios = {
            "categoria": resultado.categoria,
            "prioridad": resultado.prioridad,
            "resumen_ia": resultado.justificacion,
        }
    cambios["actualizado_en"] = to_iso(clock())
    asignaciones = ", ".join(f"{columna} = ?" for columna in cambios)
    conn.execute(f"UPDATE tickets SET {asignaciones} WHERE id = ?", [*cambios.values(), ticket_id])
    conn.commit()
    return obtener_ticket(conn, ticket_id)


def obtener_ticket(conn: sqlite3.Connection, ticket_id: int) -> TicketSalida:
    row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if row is None:
        raise TicketNoEncontradoError(ticket_id)
    return _a_salida(row)


def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _construir_where(
    *,
    estado: str | None,
    categoria: str | None,
    prioridad: str | None,
    asignado_a: int | str | None,
    q: str | None,
    columnas_busqueda: tuple[str, ...],
) -> tuple[str, list[object]]:
    condiciones: list[str] = []
    parametros: list[object] = []
    for columna, valor in (
        ("estado", estado),
        ("categoria", categoria),
        ("prioridad", prioridad),
    ):
        if valor is not None:
            condiciones.append(f"{columna} = ?")
            parametros.append(valor)
    if asignado_a == SIN_ASIGNAR:
        condiciones.append("asignado_a IS NULL")
    elif asignado_a is not None:
        condiciones.append("asignado_a = ?")
        parametros.append(asignado_a)
    q = (q or "").strip()
    if q:
        patron = f"%{_escapar_like(q)}%"
        condiciones.append(
            "(" + " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in columnas_busqueda) + ")"
        )
        parametros.extend([patron] * len(columnas_busqueda))
    where = f" WHERE {' AND '.join(condiciones)}" if condiciones else ""
    return where, parametros


def listar_bandeja(
    conn: sqlite3.Connection,
    *,
    page: int = 1,
    page_size: int = TAMANO_PAGINA_BANDEJA,
    estado: str | None = None,
    categoria: str | None = None,
    prioridad: str | None = None,
    asignado_a: int | str | None = None,
    q: str | None = None,
) -> PaginaBandeja:
    """Página de tickets para la bandeja, con el nombre del asignado.

    `asignado_a` admite un id de usuario o `SIN_ASIGNAR`. La búsqueda también mira los datos
    del cliente. Una página fuera de rango se ajusta a la última.
    """
    where, parametros = _construir_where(
        estado=estado,
        categoria=categoria,
        prioridad=prioridad,
        asignado_a=asignado_a,
        q=q,
        columnas_busqueda=("asunto", "descripcion", "solicitante_nombre", "solicitante_email"),
    )
    desde = "FROM tickets LEFT JOIN usuarios ON usuarios.id = tickets.asignado_a"
    total = conn.execute(f"SELECT COUNT(*) {desde}{where}", parametros).fetchone()[0]
    paginas = math.ceil(total / page_size)
    page = max(1, min(page, paginas))
    filas = conn.execute(
        "SELECT tickets.id, tickets.asunto, tickets.solicitante_nombre, tickets.categoria, "
        "tickets.prioridad, tickets.estado, tickets.asignado_a, tickets.creado_en, "
        f"usuarios.nombre AS asignado_nombre {desde}{where} "
        "ORDER BY tickets.creado_en DESC, tickets.id DESC LIMIT ? OFFSET ?",
        [*parametros, page_size, (page - 1) * page_size],
    ).fetchall()
    return PaginaBandeja(
        items=[FilaBandeja(**dict(f)) for f in filas],
        total=total,
        page=page,
        page_size=page_size,
        paginas=paginas,
    )


def listar_tickets(
    conn: sqlite3.Connection,
    *,
    page: int,
    page_size: int,
    estado: str | None = None,
    categoria: str | None = None,
    prioridad: str | None = None,
    asignado_a: int | None = None,
    q: str | None = None,
) -> PaginaTickets:
    where, parametros = _construir_where(
        estado=estado,
        categoria=categoria,
        prioridad=prioridad,
        asignado_a=asignado_a,
        q=q,
        columnas_busqueda=("asunto", "descripcion"),
    )

    total = conn.execute(f"SELECT COUNT(*) FROM tickets{where}", parametros).fetchone()[0]
    filas = conn.execute(
        f"SELECT * FROM tickets{where} ORDER BY creado_en DESC, id DESC LIMIT ? OFFSET ?",
        [*parametros, page_size, (page - 1) * page_size],
    ).fetchall()
    return PaginaTickets(
        items=[_a_salida(f) for f in filas],
        total=total,
        page=page,
        page_size=page_size,
        paginas=math.ceil(total / page_size),
    )


def actualizar_ticket(
    conn: sqlite3.Connection,
    ticket_id: int,
    cambios: dict[str, object],
    clock: Clock = system_clock,
) -> TicketSalida:
    """Aplica los `cambios` (ya validados) y devuelve el ticket actualizado."""
    actual = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if actual is None:
        raise TicketNoEncontradoError(ticket_id)

    asignado = cambios.get("asignado_a")
    if asignado is not None:
        existe = conn.execute(
            "SELECT 1 FROM usuarios WHERE id = ? AND activo = 1", (asignado,)
        ).fetchone()
        if existe is None:
            raise AsignadoInvalidoError("El usuario asignado no existe o está desactivado.")

    ahora = to_iso(clock())
    valores = dict(cambios)
    valores["actualizado_en"] = ahora
    if "estado" in cambios:
        if cambios["estado"] in ESTADOS_FINALES:
            valores["resuelto_en"] = actual["resuelto_en"] or ahora
        else:
            valores["resuelto_en"] = None

    asignaciones = ", ".join(f"{columna} = ?" for columna in valores)
    conn.execute(f"UPDATE tickets SET {asignaciones} WHERE id = ?", [*valores.values(), ticket_id])
    conn.commit()
    return obtener_ticket(conn, ticket_id)
