"""Control de acceso global: nada es visible sin sesión salvo /login, /health y /static."""

from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.db import connect
from app.services.autenticacion import get_active_user
from app.services.usuarios import Usuario

SESSION_USER_KEY = "usuario_id"
RUTAS_PUBLICAS = ("/login", "/health", "/static")


def _es_ruta(path: str, prefijo: str) -> bool:
    return path == prefijo or path.startswith(prefijo + "/")


def _usuario_de_sesion(database_path: str, user_id: object) -> Usuario | None:
    if not isinstance(user_id, int):
        return None
    conn = connect(database_path)
    try:
        return get_active_user(conn, user_id)
    finally:
        conn.close()


async def exigir_sesion(request: Request, call_next: RequestResponseEndpoint) -> Response:
    path = request.url.path
    if any(_es_ruta(path, ruta) for ruta in RUTAS_PUBLICAS):
        return await call_next(request)

    usuario = await run_in_threadpool(
        _usuario_de_sesion,
        request.app.state.settings.database_path,
        request.session.get(SESSION_USER_KEY),
    )
    if usuario is None:
        request.session.clear()
        if _es_ruta(path, "/api"):
            return JSONResponse({"detail": "No autenticado"}, status_code=401)
        return RedirectResponse("/login", status_code=303)

    request.state.usuario = usuario
    return await call_next(request)
