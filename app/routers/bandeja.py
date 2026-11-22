import sqlite3
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.clock import Clock, get_clock
from app.db import get_db
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

MAX_ENTERO_SQLITE = 2**63 - 1

Db = Annotated[sqlite3.Connection, Depends(get_db)]
RelojDep = Annotated[Clock, Depends(get_clock)]


def _opcion(valor: str, validos: tuple[str, ...]) -> str | None:
    """Un filtro vacío o desconocido equivale a «sin filtrar»."""
    valor = valor.strip()
    return valor if valor in validos else None


def _entero(valor: str, minimo: int) -> int | None:
    try:
        numero = int(valor)
    except ValueError:
        return None
    return numero if minimo <= numero <= MAX_ENTERO_SQLITE else None


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
    estado_f = _opcion(estado, tuple(ETIQUETAS_ESTADO))
    categoria_f = _opcion(categoria, tuple(ETIQUETAS_CATEGORIA))
    prioridad_f = _opcion(prioridad, tuple(ETIQUETAS_PRIORIDAD))
    solo_mios = mios == "1"
    solo_vencidos = vencidos == "1"
    asignado_f: int | str | None
    if solo_mios:
        asignado_f = usuario.id
    elif asignado_a == SIN_ASIGNAR:
        asignado_f = SIN_ASIGNAR
    else:
        asignado_f = _entero(asignado_a, 1)
    q = q.strip()

    resultado = listar_bandeja(
        conn,
        page=_entero(page, 1) or 1,
        estado=estado_f,
        categoria=categoria_f,
        prioridad=prioridad_f,
        asignado_a=asignado_f,
        q=q,
        solo_vencidos=solo_vencidos,
        clock=reloj,
    )

    filtros = {
        "estado": estado_f or "",
        "categoria": categoria_f or "",
        "prioridad": prioridad_f or "",
        "asignado_a": "" if solo_mios or asignado_f is None else str(asignado_f),
        "mios": "1" if solo_mios else "",
        "vencidos": "1" if solo_vencidos else "",
        "q": q,
    }

    def url_pagina(numero: int) -> str:
        parametros = {k: v for k, v in filtros.items() if v}
        parametros["page"] = numero
        return f"/bandeja?{urlencode(parametros)}"

    ahora = reloj()
    contexto = {
        "usuario": usuario,
        "pagina": resultado,
        "filtros": filtros,
        "url_pagina": url_pagina,
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
