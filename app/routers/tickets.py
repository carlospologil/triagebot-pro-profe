import sqlite3
from typing import Annotated

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

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

Db = Annotated[sqlite3.Connection, Depends(get_db)]
RelojDep = Annotated[Clock, Depends(get_clock)]

_NO_ENCONTRADO = {404: {"description": "El ticket no existe."}}


@router.post("", response_model=TicketSalida, status_code=status.HTTP_201_CREATED)
def crear(datos: TicketCrear, conn: Db, clock: RelojDep):
    """Crea un ticket en estado `nuevo`."""
    return servicio.crear_ticket(conn, datos, clock)


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
