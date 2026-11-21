import os

# app.main crea `app` al importarse y necesita SECRET_KEY.
os.environ.setdefault("SECRET_KEY", "clave-solo-para-tests")

from datetime import UTC, datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import connect, migrate  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.clasificador import get_cliente_llm  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        secret_key="clave-solo-para-tests",
        database_path=str(tmp_path / "test.db"),
    )


@pytest.fixture
def db(settings):
    """Conexión a una base de datos temporal (distinta por test) ya migrada."""
    conn = connect(settings.database_path)
    migrate(conn)
    yield conn
    conn.close()


class RelojFalso:
    """Reloj controlable: `reloj()` devuelve la hora fijada; `avanzar` la mueve."""

    def __init__(self) -> None:
        self.ahora = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.ahora

    def avanzar(self, **kwargs) -> None:
        self.ahora += timedelta(**kwargs)


@pytest.fixture
def reloj() -> RelojFalso:
    return RelojFalso()


RESPUESTA_LLM_VALIDA = (
    '{"categoria": "otro", "prioridad": "media", "justificacion": "Consulta general."}'
)


class FalsoLLM:
    """Sustituye al cliente openai: devuelve `contenido` o lanza `error`; guarda las llamadas."""

    def __init__(self, contenido: str | None = RESPUESTA_LLM_VALIDA, error=None) -> None:
        self.contenido = contenido
        self.error = error
        self.llamadas: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.llamadas.append(kwargs)
        if self.error is not None:
            raise self.error
        mensaje = SimpleNamespace(content=self.contenido)
        return SimpleNamespace(choices=[SimpleNamespace(message=mensaje)])


@pytest.fixture
def llm() -> FalsoLLM:
    return FalsoLLM()


@pytest.fixture
def client(settings, reloj, llm) -> TestClient:
    application = create_app(settings, clock=reloj)
    application.dependency_overrides[get_cliente_llm] = lambda: llm
    with TestClient(application) as test_client:
        yield test_client
