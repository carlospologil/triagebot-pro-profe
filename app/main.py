from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.clock import Clock, system_clock
from app.config import Settings, load_settings
from app.db import init_db
from app.middleware import exigir_sesion
from app.routers import bandeja, health, sesion

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    init_db(application.state.settings.database_path)
    yield


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
    return application


app = create_app()
