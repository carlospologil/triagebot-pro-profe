import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import MIN_PASSWORD_LENGTH, PasswordTooShortError
from app.clock import Clock, get_clock
from app.db import get_db
from app.middleware import CUENTA_URL
from app.permisos import require_role
from app.services import usuarios as servicio
from app.services.usuarios import Usuario
from app.templating import templates

router = APIRouter()

cualquier_usuario = require_role(*servicio.ROLES)
CLAVE_AVISO = "aviso_cuenta"


def _pagina(request: Request, usuario: Usuario, *, error: str | None = None, status: int = 200):
    contexto = {
        "usuario": usuario,
        "error": error,
        "aviso": request.session.pop(CLAVE_AVISO, None),
        "min_password": MIN_PASSWORD_LENGTH,
    }
    return templates.TemplateResponse(request, "cuenta.html", contexto, status_code=status)


@router.get("/mi-cuenta", response_class=HTMLResponse)
def ver_cuenta(request: Request, usuario: Annotated[Usuario, Depends(cualquier_usuario)]):
    return _pagina(request, usuario)


@router.post("/mi-cuenta/password", response_class=HTMLResponse)
def cambiar_password(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    usuario: Annotated[Usuario, Depends(cualquier_usuario)],
    reloj: Annotated[Clock, Depends(get_clock)],
    actual: Annotated[str, Form()] = "",
    nueva: Annotated[str, Form()] = "",
    confirmacion: Annotated[str, Form()] = "",
):
    if nueva != confirmacion:
        return _pagina(request, usuario, error="La confirmación no coincide.", status=422)
    try:
        servicio.cambiar_password(conn, usuario.id, actual, nueva, clock=reloj)
    except (servicio.UsuarioError, PasswordTooShortError) as exc:
        return _pagina(request, usuario, error=str(exc), status=422)
    request.session[CLAVE_AVISO] = "Contraseña actualizada."
    return RedirectResponse(CUENTA_URL, status_code=303)
