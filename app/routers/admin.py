import sqlite3
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import PasswordTooShortError
from app.clock import Clock, get_clock
from app.db import get_db
from app.flash import flash
from app.permisos import require_role
from app.services import auditoria
from app.services import usuarios as servicio
from app.services.formato import formatear_fecha, valor_auditoria
from app.services.usuarios import Usuario
from app.templating import templates

solo_admin = require_role("admin")

# La dependencia a nivel de router protege también las rutas /admin que se añadan después.
router = APIRouter(prefix="/admin", dependencies=[Depends(solo_admin)])

Db = Annotated[sqlite3.Connection, Depends(get_db)]
Reloj = Annotated[Clock, Depends(get_clock)]
Admin = Annotated[Usuario, Depends(solo_admin)]

USUARIOS_URL = "/admin/usuarios"


@router.get("", response_class=HTMLResponse)
def panel(request: Request, usuario: Annotated[Usuario, Depends(solo_admin)]):
    return templates.TemplateResponse(request, "admin.html", {"usuario": usuario})


def _pagina_usuarios(
    request: Request,
    conn: sqlite3.Connection,
    usuario: Usuario,
    *,
    error: str | None = None,
    errores: dict[str, str] | None = None,
    status: int = 200,
    temporal: tuple[str, str] | None = None,
    formulario: dict[str, str] | None = None,
):
    """Lista de usuarios. `temporal` es (email, contraseña) y solo se muestra en esta respuesta.

    `errores` asocia mensajes a campos del formulario de alta; `error` es un fallo general."""
    if errores:
        flash(request, "No se ha creado el usuario: revisa los campos marcados.", "error")
    elif error:
        flash(request, error, "error")
    contexto = {
        "usuario": usuario,
        "usuarios": servicio.listar_usuarios(conn),
        "roles": servicio.ROLES,
        "opciones_rol": [
            (r, "Administrador" if r == "admin" else "Agente") for r in servicio.ROLES
        ],
        "errores": errores or {},
        "temporal": temporal,
        "formulario": formulario or {"email": "", "nombre": "", "rol": "agente"},
        "fecha": formatear_fecha,
    }
    respuesta = templates.TemplateResponse(request, "usuarios.html", contexto, status_code=status)
    if temporal:
        respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


def _fallo(request: Request, conn: sqlite3.Connection, usuario: Usuario, exc: ValueError):
    if isinstance(exc, servicio.UsuarioNoEncontradoError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    status = 409 if isinstance(exc, servicio.ProteccionError) else 422
    return _pagina_usuarios(request, conn, usuario, error=str(exc), status=status)


def _hecho(request: Request, aviso: str) -> RedirectResponse:
    flash(request, aviso)
    return RedirectResponse(USUARIOS_URL, status_code=303)


@router.get("/usuarios", response_class=HTMLResponse)
def listar_usuarios(request: Request, conn: Db, usuario: Admin):
    return _pagina_usuarios(request, conn, usuario)


@router.post("/usuarios", response_class=HTMLResponse)
def crear_usuario(
    request: Request,
    conn: Db,
    usuario: Admin,
    reloj: Reloj,
    email: Annotated[str, Form()] = "",
    nombre: Annotated[str, Form()] = "",
    rol: Annotated[str, Form()] = "agente",
    password: Annotated[str, Form()] = "",
):
    """Alta de usuario. Sin contraseña indicada se genera una temporal; siempre debe cambiarla."""
    formulario = {"email": email, "nombre": nombre, "rol": rol}
    inicial = password or servicio.generar_password_temporal()
    try:
        nuevo = servicio.create_user(
            conn,
            email=email,
            nombre=nombre,
            password=inicial,
            rol=rol,
            clock=reloj,
            actor_id=usuario.id,
            debe_cambiar_password=True,
        )
    except (servicio.UsuarioError, PasswordTooShortError) as exc:
        status = 409 if isinstance(exc, servicio.EmailDuplicadoError) else 422
        if isinstance(exc, PasswordTooShortError):
            campo = "password"
        else:
            campo = getattr(exc, "campo", None)
        if campo is None:
            return _pagina_usuarios(
                request, conn, usuario, error=str(exc), status=status, formulario=formulario
            )
        return _pagina_usuarios(
            request, conn, usuario, errores={campo: str(exc)}, status=status, formulario=formulario
        )
    if password:
        return _hecho(request, f"Usuario {nuevo.email} creado. Deberá cambiar la contraseña.")
    flash(request, f"Usuario {nuevo.email} creado con una contraseña temporal.")
    return _pagina_usuarios(request, conn, usuario, temporal=(nuevo.email, inicial))


@router.post("/usuarios/{user_id}/rol", response_class=HTMLResponse)
def cambiar_rol(
    request: Request,
    user_id: int,
    conn: Db,
    usuario: Admin,
    reloj: Reloj,
    rol: Annotated[str, Form()] = "",
):
    try:
        actualizado = servicio.cambiar_rol(conn, user_id, rol, actor_id=usuario.id, clock=reloj)
    except servicio.UsuarioError as exc:
        return _fallo(request, conn, usuario, exc)
    return _hecho(request, f"Rol de {actualizado.email} actualizado.")


@router.post("/usuarios/{user_id}/desactivar", response_class=HTMLResponse)
def desactivar_usuario(request: Request, user_id: int, conn: Db, usuario: Admin, reloj: Reloj):
    try:
        actualizado = servicio.desactivar(conn, user_id, actor_id=usuario.id, clock=reloj)
    except servicio.UsuarioError as exc:
        return _fallo(request, conn, usuario, exc)
    return _hecho(request, f"Usuario {actualizado.email} desactivado.")


@router.post("/usuarios/{user_id}/reactivar", response_class=HTMLResponse)
def reactivar_usuario(request: Request, user_id: int, conn: Db, usuario: Admin, reloj: Reloj):
    try:
        actualizado = servicio.reactivar(conn, user_id, actor_id=usuario.id, clock=reloj)
    except servicio.UsuarioError as exc:
        return _fallo(request, conn, usuario, exc)
    return _hecho(request, f"Usuario {actualizado.email} reactivado.")


@router.post("/usuarios/{user_id}/restablecer", response_class=HTMLResponse)
def restablecer_password(request: Request, user_id: int, conn: Db, usuario: Admin, reloj: Reloj):
    """Muestra la contraseña temporal en esta respuesta; no se guarda en ningún otro sitio."""
    try:
        temporal = servicio.restablecer_password(conn, user_id, actor_id=usuario.id, clock=reloj)
    except servicio.UsuarioError as exc:
        return _fallo(request, conn, usuario, exc)
    destino = servicio.get_user(conn, user_id)
    flash(request, f"Contraseña de {destino.email} restablecida.")
    return _pagina_usuarios(request, conn, usuario, temporal=(destino.email, temporal))


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
    status = 200
    try:
        pagina = auditoria.listar(conn, page=page, **filtros)
    except auditoria.FiltroInvalidoError as exc:
        flash(request, str(exc), "error")
        status = 422
        pagina = auditoria.PaginaAuditoria(
            items=[], total=0, page=1, page_size=auditoria.TAMANO_PAGINA, paginas=0
        )
    consulta = urlencode({k: v for k, v in filtros.items() if v})
    contexto = {
        "usuario": usuario,
        "pagina": pagina,
        "filtros": filtros,
        "filtro_invalido": status == 422,
        "consulta": consulta + "&" if consulta else "",
        "usuarios": conn.execute(
            "SELECT id, nombre, email FROM usuarios ORDER BY nombre, id"
        ).fetchall(),
        "acciones": auditoria.ETIQUETAS_ACCION,
        "fecha": formatear_fecha,
        "valor_auditoria": valor_auditoria,
    }
    return templates.TemplateResponse(request, "auditoria.html", contexto, status_code=status)
