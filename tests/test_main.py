import re
from pathlib import Path

import pytest
from fastapi import FastAPI

from app.config import ConfigError
from app.main import app, create_app

ROOT = Path(__file__).resolve().parent.parent


def test_expone_app_y_create_app(settings):
    assert isinstance(app, FastAPI)
    assert isinstance(create_app(settings), FastAPI)


def test_create_app_sin_secret_key_falla(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ConfigError, match="SECRET_KEY"):
        create_app()


def test_requirements_fijadas_con_igual_doble():
    lines = [
        ln.strip()
        for ln in (ROOT / "requirements.txt").read_text().splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    assert all(re.fullmatch(r"[A-Za-z0-9_.-]+==[\w.]+", ln) for ln in lines)
    names = {ln.split("==")[0].lower() for ln in lines}
    required = {
        "fastapi", "uvicorn", "jinja2", "python-multipart", "itsdangerous",
        "openai", "pytest", "httpx", "ruff",
    }  # fmt: skip
    assert required <= names


def test_env_example_lista_variables():
    text = (ROOT / ".env.example").read_text()
    for var in ("SECRET_KEY", "DATABASE_PATH", "OPENROUTER_API_KEY"):
        assert re.search(rf"^{var}=", text, re.MULTILINE)
    assert "#" in text


def test_uvicorn_puede_cargar_app_main_app():
    import uvicorn

    config = uvicorn.Config("app.main:app")
    config.load()
    assert config.loaded_app is not None
