from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

from app.clock import Clock, system_clock
from app.config import Settings, load_settings
from app.db import init_db
from app.middleware import exigir_sesion
from app.routers import admin, bandeja, health, sesion
from app.templating import templates

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    init_db(application.state.settings.database_path)
    yield


async def _manejar_http(request: Request, exc: StarletteHTTPException) -> Response:
    """Los 403 de páginas se muestran como HTML; el resto, y las rutas /api, como siempre."""
    if exc.status_code == 403 and not request.url.path.startswith("/api"):
        return templates.TemplateResponse(
            request, "prohibido.html", {"mensaje": exc.detail}, status_code=403
        )
    return await http_exception_handler(request, exc)


def create_app(settings: Settings | None = None, clock: Clock = system_clock) -> FastAPI:
    settings = settings or load_settings()
    application = FastAPI(title="TriageBot Pro", lifespan=lifespan)
    application.state.settings = settings
    application.state.clock = clock
    # El último middleware añadido es el más externo: la sesión debe cargarse antes
    # de comprobar el acceso.
    application.add_middleware(BaseHTTPMiddleware, dispatch=exigir_sesion)
    application.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax")
    application.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    application.include_router(health.router)
    application.include_router(sesion.router)
    application.include_router(bandeja.router)
    application.include_router(admin.router)
    application.add_exception_handler(StarletteHTTPException, _manejar_http)
    return application


app = create_app()
