"""Pantalla de detalle de un ticket y sus acciones (estado, asignación y corrección de la IA).

Cada acción responde con el panel afectado (HTMX) más la caja de fechas como actualización
«fuera de banda»; sin HTMX redirige al detalle (o lo vuelve a pintar con el error).
"""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.clock import Clock, get_clock
from app.db import get_db
from app.flash import flash
from app.services import auditoria, comentarios
from app.services import tickets as servicio
from app.services.formato import (
    ETIQUETAS_CATEGORIA,
    ETIQUETAS_ESTADO,
    ETIQUETAS_PRIORIDAD,
    formatear_fecha,
    valor_auditoria,
)
from app.services.sla import calcular_plazo
from app.services.usuarios import get_user, listar_usuarios_activos
from app.templating import templates

router = APIRouter(prefix="/tickets")

MAX_ENTERO_SQLITE = 2**63 - 1
MENSAJES_OK = {
    "estado": "Estado actualizado.",
    "asignacion": "Asignación actualizada.",
    "clasificacion": "Clasificación corregida.",
    "comentarios": "Comentario añadido.",
}
MENSAJE_ERROR = "No se ha guardado el cambio: revisa el error indicado."

Db = Annotated[sqlite3.Connection, Depends(get_db)]
RelojDep = Annotated[Clock, Depends(get_clock)]


def _es_htmx(request: Request) -> bool:
    return (
        request.headers.get("HX-Request") == "true"
        and request.headers.get("HX-History-Restore-Request") != "true"
    )


def _cargar(conn: sqlite3.Connection, ticket_id: int):
    try:
        return servicio.obtener_ticket(conn, ticket_id)
    except servicio.TicketNoEncontradoError:
        raise HTTPException(status_code=404, detail="Ticket no encontrado") from None


def _contexto(
    request: Request,
    conn: sqlite3.Connection,
    ticket,
    errores: dict[str, str],
    borrador: str = "",
):
    agentes = listar_usuarios_activos(conn)
    asignado = get_user(conn, ticket.asignado_a) if ticket.asignado_a else None
    return {
        "request": request,
        "usuario": request.state.usuario,
        "t": ticket,
        "errores": errores,
        "siguientes": servicio.transiciones_permitidas(ticket.estado),
        "agentes": agentes,
        "asignado": asignado,
        "asignado_inactivo": asignado is not None and all(a.id != asignado.id for a in agentes),
        "etiquetas_estado": ETIQUETAS_ESTADO,
        "etiquetas_prioridad": ETIQUETAS_PRIORIDAD,
        "etiquetas_categoria": ETIQUETAS_CATEGORIA,
        "fecha": formatear_fecha,
        "historial": comentarios.linea_de_tiempo(conn, ticket.id),
        "borrador": borrador,
        "max_comentario": comentarios.MAX_CARACTERES,
        "etiquetas_accion": auditoria.ETIQUETAS_ACCION,
        "valor_auditoria": valor_auditoria,
        "plazo": calcular_plazo(ticket.fecha_limite, ticket.estado, get_clock(request)()),
        "oob": False,
    }


def _pagina(
    request: Request,
    conn,
    ticket_id: int,
    errores: dict[str, str],
    status: int,
    borrador: str = "",
):
    contexto = _contexto(request, conn, _cargar(conn, ticket_id), errores, borrador)
    respuesta = templates.TemplateResponse(request, "ticket.html", contexto, status_code=status)
    respuesta.headers["Vary"] = "HX-Request"
    return respuesta


def _resultado(
    request: Request,
    conn,
    ticket_id: int,
    panel: str,
    error: str | None = None,
    status: int = 409,
    borrador: str = "",
) -> Response:
    """Respuesta de una acción: fragmento HTMX, redirección o página completa con el error."""
    mensaje = (MENSAJES_OK[panel], "ok") if error is None else (MENSAJE_ERROR, "error")
    if not _es_htmx(request):
        flash(request, *mensaje)
        if error is None:
            return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)
        return _pagina(request, conn, ticket_id, {panel: error}, status, borrador)
    contexto = _contexto(
        request, conn, _cargar(conn, ticket_id), {panel: error} if error else {}, borrador
    )
    html = templates.get_template(f"_panel_{panel}.html").render(contexto)
    html += templates.get_template("_flash.html").render(
        {"mensajes": [(mensaje[1], mensaje[0])], "oob": True}
    )
    html += templates.get_template("_fechas.html").render({**contexto, "oob": True})
    html += templates.get_template("_historial.html").render({**contexto, "oob": True})
    return HTMLResponse(
        html, status_code=200 if error is None else status, headers={"Vary": "HX-Request"}
    )


@router.get("/{ticket_id}", response_class=HTMLResponse)
def detalle(ticket_id: int, request: Request, conn: Db):
    return _pagina(request, conn, ticket_id, {}, 200)


@router.post("/{ticket_id}/estado", response_class=HTMLResponse)
def cambiar_estado(
    ticket_id: int,
    request: Request,
    conn: Db,
    reloj: RelojDep,
    estado: Annotated[str, Form()] = "",
):
    _cargar(conn, ticket_id)
    estado = estado.strip()
    if estado not in ETIQUETAS_ESTADO:
        return _resultado(request, conn, ticket_id, "estado", "Elige un estado válido.", 422)
    try:
        servicio.actualizar_ticket(
            conn, ticket_id, {"estado": estado}, reloj, usuario_id=request.state.usuario.id
        )
    except servicio.TransicionNoPermitidaError as exc:
        return _resultado(request, conn, ticket_id, "estado", str(exc), 409)
    return _resultado(request, conn, ticket_id, "estado")


@router.post("/{ticket_id}/asignacion", response_class=HTMLResponse)
def asignar(
    ticket_id: int,
    request: Request,
    conn: Db,
    reloj: RelojDep,
    asignado_a: Annotated[str, Form()] = "",
):
    _cargar(conn, ticket_id)
    asignado_a = asignado_a.strip()
    destino: int | None = None
    if asignado_a:
        try:
            destino = int(asignado_a)
        except ValueError:
            destino = 0
        if not 1 <= destino <= MAX_ENTERO_SQLITE:
            return _resultado(request, conn, ticket_id, "asignacion", "Persona no válida.", 422)
    try:
        servicio.actualizar_ticket(
            conn, ticket_id, {"asignado_a": destino}, reloj, usuario_id=request.state.usuario.id
        )
    except servicio.AsignadoInvalidoError as exc:
        return _resultado(request, conn, ticket_id, "asignacion", str(exc), 422)
    return _resultado(request, conn, ticket_id, "asignacion")


@router.post("/{ticket_id}/clasificacion", response_class=HTMLResponse)
def corregir_clasificacion(
    ticket_id: int,
    request: Request,
    conn: Db,
    reloj: RelojDep,
    categoria: Annotated[str, Form()] = "",
    prioridad: Annotated[str, Form()] = "",
):
    _cargar(conn, ticket_id)
    cambios: dict[str, object] = {}
    for campo, valor, validos in (
        ("categoria", categoria.strip(), ETIQUETAS_CATEGORIA),
        ("prioridad", prioridad.strip(), ETIQUETAS_PRIORIDAD),
    ):
        if not valor:
            continue
        if valor not in validos:
            return _resultado(
                request, conn, ticket_id, "clasificacion", f"Valor no válido para {campo}.", 422
            )
        cambios[campo] = valor
    if not cambios:
        return _resultado(
            request, conn, ticket_id, "clasificacion", "Elige una categoría o una prioridad.", 422
        )
    servicio.actualizar_ticket(conn, ticket_id, cambios, reloj, usuario_id=request.state.usuario.id)
    return _resultado(request, conn, ticket_id, "clasificacion")


@router.post("/{ticket_id}/comentarios", response_class=HTMLResponse)
def comentar(
    ticket_id: int,
    request: Request,
    conn: Db,
    reloj: RelojDep,
    cuerpo: Annotated[str, Form()] = "",
):
    _cargar(conn, ticket_id)
    try:
        comentarios.crear_comentario(conn, ticket_id, request.state.usuario.id, cuerpo, reloj)
    except comentarios.ComentarioInvalidoError as exc:
        return _resultado(
            request,
            conn,
            ticket_id,
            "comentarios",
            str(exc),
            422,
            borrador=comentarios.normalizar(cuerpo),
        )
    return _resultado(request, conn, ticket_id, "comentarios")
