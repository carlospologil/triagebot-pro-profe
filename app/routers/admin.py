import sqlite3
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from app.db import get_db
from app.permisos import require_role
from app.services import auditoria
from app.services.formato import formatear_fecha, valor_auditoria
from app.services.usuarios import Usuario
from app.templating import templates

solo_admin = require_role("admin")

# La dependencia a nivel de router protege también las rutas /admin que se añadan después.
router = APIRouter(prefix="/admin", dependencies=[Depends(solo_admin)])

Db = Annotated[sqlite3.Connection, Depends(get_db)]


@router.get("", response_class=HTMLResponse)
def panel(request: Request, usuario: Annotated[Usuario, Depends(solo_admin)]):
    return templates.TemplateResponse(request, "admin.html", {"usuario": usuario})


@router.get("/auditoria", response_class=HTMLResponse)
def ver_auditoria(
    request: Request,
    conn: Db,
    usuario: Annotated[Usuario, Depends(solo_admin)],
    page: Annotated[int, Query(ge=1)] = 1,
    usuario_filtro: Annotated[str, Query(alias="usuario")] = "",
    accion: str = "",
    desde: str = "",
    hasta: str = "",
):
    """Registros de auditoría, solo lectura, con filtros por usuario, acción y fechas."""
    filtros = {
        "usuario": usuario_filtro.strip(),
        "accion": accion.strip(),
        "desde": desde.strip(),
        "hasta": hasta.strip(),
    }
    error = None
    status = 200
    try:
        pagina = auditoria.listar(conn, page=page, **filtros)
    except auditoria.FiltroInvalidoError as exc:
        error, status = str(exc), 422
        pagina = auditoria.PaginaAuditoria(
            items=[], total=0, page=1, page_size=auditoria.TAMANO_PAGINA, paginas=0
        )
    consulta = urlencode({k: v for k, v in filtros.items() if v})
    contexto = {
        "usuario": usuario,
        "pagina": pagina,
        "filtros": filtros,
        "error": error,
        "consulta": consulta + "&" if consulta else "",
        "usuarios": conn.execute(
            "SELECT id, nombre, email FROM usuarios ORDER BY nombre, id"
        ).fetchall(),
        "acciones": auditoria.ETIQUETAS_ACCION,
        "fecha": formatear_fecha,
        "valor_auditoria": valor_auditoria,
    }
    return templates.TemplateResponse(request, "auditoria.html", contexto, status_code=status)
