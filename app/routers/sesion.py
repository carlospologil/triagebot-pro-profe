import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.clock import Clock, get_clock
from app.db import get_db
from app.flash import flash
from app.middleware import SESSION_USER_KEY
from app.services.autenticacion import authenticate
from app.templating import templates

router = APIRouter()

BANDEJA_URL = "/bandeja"
MENSAJE_CREDENCIALES = (
    "Email o contraseña incorrectos, o acceso bloqueado temporalmente. "
    "Inténtalo de nuevo más tarde."
)


@router.get("/login", response_class=HTMLResponse)
def formulario_login(request: Request):
    if request.session.get(SESSION_USER_KEY) is not None:
        return RedirectResponse(BANDEJA_URL, status_code=303)
    return templates.TemplateResponse(request, "login.html", {"email": ""})


@router.post("/login", response_class=HTMLResponse)
def iniciar_sesion(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    clock: Annotated[Clock, Depends(get_clock)],
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
):
    usuario = authenticate(conn, email, password, clock)
    if usuario is None:
        flash(request, MENSAJE_CREDENCIALES, "error")
        return templates.TemplateResponse(request, "login.html", {"email": email}, status_code=401)
    request.session.clear()
    request.session[SESSION_USER_KEY] = usuario.id
    return RedirectResponse(BANDEJA_URL, status_code=303)


@router.post("/logout")
def cerrar_sesion(request: Request):
    request.session.clear()
    flash(request, "Has cerrado sesión.")
    return RedirectResponse("/login", status_code=303)
