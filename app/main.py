import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse, Response

from app.clock import Clock, system_clock
from app.config import Settings, load_settings
from app.db import connect, init_db
from app.middleware import exigir_sesion
from app.routers import admin, bandeja, cuenta, detalle, health, panel, sesion, tickets
from app.seguridad import CabecerasSeguridadMiddleware, CsrfMiddleware, aplicar_cabeceras_seguridad
from app.services import sla
from app.templating import templates

BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    ruta = application.state.settings.database_path
    init_db(ruta)
    conn = connect(ruta)
    try:
        sla.rellenar_fechas_limite(conn)
    finally:
        conn.close()
    yield


async def _manejar_http(request: Request, exc: StarletteHTTPException) -> Response:
    """Los 403 y los 404 de las páginas se muestran como HTML propio (la API responde JSON)."""
    ruta = request.url.path
    if not _es_api(ruta):
        if exc.status_code == 403:
            return templates.TemplateResponse(
                request, "prohibido.html", {"mensaje": exc.detail}, status_code=403
            )
        if exc.status_code == 404:
            es_ticket = ruta.startswith("/tickets/")
            plantilla = "no_encontrado.html" if es_ticket else "pagina_no_encontrada.html"
            return templates.TemplateResponse(request, plantilla, {}, status_code=404)
    return await http_exception_handler(request, exc)


def _es_api(ruta: str) -> bool:
    return ruta == "/api" or ruta.startswith("/api/")


async def _manejar_error_interno(request: Request, exc: Exception) -> Response:
    """Error 500 sin trazas ni detalles: la causa solo queda en el log del servidor.

    Este manejador corre fuera de los middlewares, así que añade él mismo las cabeceras."""
    logger.error("Error no controlado en %s %s", request.method, request.url.path, exc_info=exc)
    if _es_api(request.url.path):
        respuesta: Response = JSONResponse({"detail": "Error interno del servidor"}, 500)
    else:
        respuesta = templates.TemplateResponse(request, "error_interno.html", {}, status_code=500)
    aplicar_cabeceras_seguridad(respuesta.headers)
    return respuesta


def create_app(settings: Settings | None = None, clock: Clock = system_clock) -> FastAPI:
    settings = settings or load_settings()
    application = FastAPI(title="TriageBot Pro", lifespan=lifespan)
    application.state.settings = settings
    application.state.clock = clock
    # El último middleware añadido es el más externo: la sesión debe cargarse antes
    # de comprobar el acceso.
    application.add_middleware(BaseHTTPMiddleware, dispatch=exigir_sesion)
    application.add_middleware(CsrfMiddleware)
    application.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax")
    application.add_middleware(CabecerasSeguridadMiddleware)
    application.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    application.include_router(health.router)
    application.include_router(sesion.router)
    application.include_router(bandeja.router)
    application.include_router(detalle.router)
    application.include_router(admin.router)
    application.include_router(cuenta.router)
    application.include_router(panel.router)
    application.include_router(tickets.router)
    application.add_exception_handler(StarletteHTTPException, _manejar_http)
    application.add_exception_handler(Exception, _manejar_error_interno)
    return application


app = create_app()
