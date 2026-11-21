"""Alta, consulta y actualización de tickets."""

import math
import sqlite3

from app.clock import Clock, system_clock, to_iso
from app.schemas import ESTADOS_FINALES, PaginaTickets, TicketCrear, TicketSalida

CAMPOS_EDITABLES = ("estado", "prioridad", "categoria", "asignado_a")


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


def obtener_ticket(conn: sqlite3.Connection, ticket_id: int) -> TicketSalida:
    row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if row is None:
        raise TicketNoEncontradoError(ticket_id)
    return _a_salida(row)


def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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
    condiciones: list[str] = []
    parametros: list[object] = []
    for columna, valor in (
        ("estado", estado),
        ("categoria", categoria),
        ("prioridad", prioridad),
        ("asignado_a", asignado_a),
    ):
        if valor is not None:
            condiciones.append(f"{columna} = ?")
            parametros.append(valor)
    q = (q or "").strip()
    if q:
        patron = f"%{_escapar_like(q)}%"
        condiciones.append("(asunto LIKE ? ESCAPE '\\' OR descripcion LIKE ? ESCAPE '\\')")
        parametros.extend([patron, patron])
    where = f" WHERE {' AND '.join(condiciones)}" if condiciones else ""

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
