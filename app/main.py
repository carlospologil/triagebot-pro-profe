from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import Settings, load_settings
from app.routers import health

BASE_DIR = Path(__file__).resolve().parent


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    application = FastAPI(title="TriageBot Pro")
    application.state.settings = settings
    application.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
    application.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    application.include_router(health.router)
    return application


app = create_app()
