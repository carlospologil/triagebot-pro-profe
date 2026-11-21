import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.clock import Clock, get_clock
from app.db import get_db
from app.schemas import (
    Categoria,
    Estado,
    PaginaTickets,
    Prioridad,
    TicketActualizar,
    TicketCrear,
    TicketSalida,
)
from app.services import tickets as servicio
from app.services.clasificador import ClasificacionError, get_cliente_llm

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

Db = Annotated[sqlite3.Connection, Depends(get_db)]
RelojDep = Annotated[Clock, Depends(get_clock)]
LlmDep = Annotated[Any, Depends(get_cliente_llm)]

_NO_ENCONTRADO = {404: {"description": "El ticket no existe."}}


@router.post("", response_model=TicketSalida, status_code=status.HTTP_201_CREATED)
def crear(datos: TicketCrear, conn: Db, clock: RelojDep, llm: LlmDep):
    """Crea un ticket en estado `nuevo` y lo clasifica con IA (si falla, queda `sin_clasificar`)."""
    ticket = servicio.crear_ticket(conn, datos, clock)
    return servicio.clasificar_ticket(conn, ticket.id, llm, clock, marcar_sin_clasificar=True)


@router.post(
    "/{ticket_id}/reclasificar",
    response_model=TicketSalida,
    responses={**_NO_ENCONTRADO, 502: {"description": "La IA no pudo clasificar el ticket."}},
)
def reclasificar(ticket_id: int, conn: Db, clock: RelojDep, llm: LlmDep):
    """Vuelve a clasificar el ticket con IA. Si la IA falla, el ticket no cambia."""
    try:
        return servicio.clasificar_ticket(conn, ticket_id, llm, clock)
    except servicio.TicketNoEncontradoError:
        raise HTTPException(status_code=404, detail="Ticket no encontrado") from None
    except ClasificacionError:
        raise HTTPException(
            status_code=502, detail="No se pudo clasificar el ticket con IA. Inténtalo de nuevo."
        ) from None


@router.get("", response_model=PaginaTickets)
def listar(
    conn: Db,
    page: Annotated[int, Query(ge=1, description="Número de página (desde 1).")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Tickets por página.")] = 20,
    estado: Estado | None = None,
    categoria: Categoria | None = None,
    prioridad: Prioridad | None = None,
    asignado_a: Annotated[int | None, Query(ge=1, description="Id del usuario asignado.")] = None,
    q: Annotated[str | None, Query(description="Busca en el asunto y el texto.")] = None,
):
    """Lista tickets, del más reciente al más antiguo, con filtros opcionales combinables."""
    return servicio.listar_tickets(
        conn,
        page=page,
        page_size=page_size,
        estado=estado,
        categoria=categoria,
        prioridad=prioridad,
        asignado_a=asignado_a,
        q=q,
    )


@router.get("/{ticket_id}", response_model=TicketSalida, responses=_NO_ENCONTRADO)
def detalle(ticket_id: int, conn: Db):
    try:
        return servicio.obtener_ticket(conn, ticket_id)
    except servicio.TicketNoEncontradoError:
        raise HTTPException(status_code=404, detail="Ticket no encontrado") from None


@router.patch("/{ticket_id}", response_model=TicketSalida, responses=_NO_ENCONTRADO)
def actualizar(ticket_id: int, datos: TicketActualizar, conn: Db, clock: RelojDep):
    """Cambia estado, prioridad, categoría y/o asignación; solo se tocan los campos enviados."""
    cambios = datos.model_dump(exclude_unset=True)
    if not cambios:
        raise HTTPException(status_code=422, detail="Indica al menos un campo que modificar")
    try:
        return servicio.actualizar_ticket(conn, ticket_id, cambios, clock)
    except servicio.TicketNoEncontradoError:
        raise HTTPException(status_code=404, detail="Ticket no encontrado") from None
    except servicio.AsignadoInvalidoError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
