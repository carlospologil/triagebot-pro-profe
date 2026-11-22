import base64
import json
import os

# app.main crea `app` al importarse y necesita SECRET_KEY.
os.environ.setdefault("SECRET_KEY", "clave-solo-para-tests")

from datetime import UTC, datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.csrf import CSRF_HEADER, CSRF_SESSION_KEY  # noqa: E402
from app.db import connect, migrate  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.clasificador import get_cliente_llm  # noqa: E402

METODOS_SEGUROS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def token_csrf_de_cookie(cliente: TestClient) -> str | None:
    """Lee el token CSRF de la cookie de sesión firmada del cliente (sin verificar la firma)."""
    cookie = cliente.cookies.get("session")
    if not cookie:
        return None
    try:
        datos = json.loads(base64.b64decode(cookie.split(".")[0]))
    except ValueError:
        return None
    return datos.get(CSRF_SESSION_KEY)


@pytest.fixture(autouse=True)
def csrf_automatico(request, monkeypatch):
    """Los tests existentes se comportan como un navegador: envían el token CSRF de su sesión.

    La protección sigue activa en la aplicación; los tests de CSRF lo desactivan con la marca
    `csrf_estricto` para enviar peticiones sin token o con uno falso."""
    if request.node.get_closest_marker("csrf_estricto"):
        return
    original = TestClient.request

    def con_token(self, method, url, *args, **kwargs):
        if method.upper() not in METODOS_SEGUROS:
            cabeceras = dict(kwargs.get("headers") or {})
            if not any(nombre.lower() == CSRF_HEADER.lower() for nombre in cabeceras):
                token = token_csrf_de_cookie(self)
                if token is None:
                    original(self, "GET", "/login")
                    token = token_csrf_de_cookie(self)
                cabeceras[CSRF_HEADER] = token or ""
                kwargs["headers"] = cabeceras
        return original(self, method, url, *args, **kwargs)

    monkeypatch.setattr(TestClient, "request", con_token)


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
