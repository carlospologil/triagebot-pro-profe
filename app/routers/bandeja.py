import sqlite3
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.clock import Clock, get_clock
from app.db import get_db
from app.services.filtros import entero, interpretar_filtros
from app.services.formato import (
    ETIQUETAS_CATEGORIA,
    ETIQUETAS_ESTADO,
    ETIQUETAS_PRIORIDAD,
    antiguedad,
)
from app.services.sla import calcular_plazo
from app.services.tickets import SIN_ASIGNAR, listar_bandeja
from app.services.usuarios import listar_usuarios_activos
from app.templating import templates

router = APIRouter()

Db = Annotated[sqlite3.Connection, Depends(get_db)]
RelojDep = Annotated[Clock, Depends(get_clock)]


@router.get("/", include_in_schema=False)
def inicio():
    return RedirectResponse("/bandeja", status_code=303)


@router.get("/bandeja", response_class=HTMLResponse)
def bandeja(
    request: Request,
    conn: Db,
    reloj: RelojDep,
    estado: Annotated[str, Query()] = "",
    categoria: Annotated[str, Query()] = "",
    prioridad: Annotated[str, Query()] = "",
    asignado_a: Annotated[str, Query()] = "",
    mios: Annotated[str, Query()] = "",
    vencidos: Annotated[str, Query()] = "",
    q: Annotated[str, Query()] = "",
    page: Annotated[str, Query()] = "1",
):
    """Bandeja completa; si la pide HTMX (HX-Request) solo devuelve la tabla.

    La restauración del historial (HX-History-Restore-Request) también lleva HX-Request,
    pero necesita la página entera.
    """
    usuario = request.state.usuario
    f = interpretar_filtros(
        usuario_id=usuario.id,
        estado=estado,
        categoria=categoria,
        prioridad=prioridad,
        asignado_a=asignado_a,
        mios=mios,
        vencidos=vencidos,
        q=q,
    )

    resultado = listar_bandeja(
        conn,
        page=entero(page, 1) or 1,
        estado=f.estado,
        categoria=f.categoria,
        prioridad=f.prioridad,
        asignado_a=f.asignado_a,
        q=f.q,
        solo_vencidos=f.solo_vencidos,
        clock=reloj,
    )

    filtros = {
        "estado": f.estado or "",
        "categoria": f.categoria or "",
        "prioridad": f.prioridad or "",
        "asignado_a": "" if f.solo_mios or f.asignado_a is None else str(f.asignado_a),
        "mios": "1" if f.solo_mios else "",
        "vencidos": "1" if f.solo_vencidos else "",
        "q": f.q,
    }
    parametros_filtros = {k: v for k, v in filtros.items() if v}

    def url_pagina(numero: int) -> str:
        return f"/bandeja?{urlencode({**parametros_filtros, 'page': numero})}"

    url_exportar = "/api/tickets/export.csv"
    if parametros_filtros:
        url_exportar += f"?{urlencode(parametros_filtros)}"

    ahora = reloj()
    contexto = {
        "usuario": usuario,
        "pagina": resultado,
        "filtros": filtros,
        "url_pagina": url_pagina,
        "url_exportar": url_exportar,
        "antiguedad": lambda iso: antiguedad(iso, ahora),
        "plazo": lambda t: calcular_plazo(t.fecha_limite, t.estado, ahora),
        "etiquetas_estado": ETIQUETAS_ESTADO,
        "etiquetas_prioridad": ETIQUETAS_PRIORIDAD,
        "etiquetas_categoria": ETIQUETAS_CATEGORIA,
        "hay_filtros": any(filtros.values()),
    }
    es_htmx = request.headers.get("HX-Request") == "true"
    restaura_historial = request.headers.get("HX-History-Restore-Request") == "true"
    if es_htmx and not restaura_historial:
        respuesta = templates.TemplateResponse(request, "_tabla_tickets.html", contexto)
    else:
        contexto["agentes"] = listar_usuarios_activos(conn)
        contexto["sin_asignar"] = SIN_ASIGNAR
        respuesta = templates.TemplateResponse(request, "bandeja.html", contexto)
    respuesta.headers["Vary"] = "HX-Request"
    return respuesta
