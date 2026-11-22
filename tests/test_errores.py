import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.usuarios import create_user

PASSWORD = "una-clave-segura"
SECRETO = "detalle-interno-secreto-xyz"


@pytest.fixture
def aplicacion(settings, reloj):
    application = create_app(settings, clock=reloj)

    def fallar():
        raise RuntimeError(SECRETO)

    application.add_api_route("/health/fallo", fallar)
    application.add_api_route("/api/fallo", fallar)
    application.add_api_route("/pagina-con-fallo", fallar)
    return application


@pytest.fixture
def navegador(aplicacion, db):
    """Cliente que, como un navegador, recibe la respuesta 500 en lugar de ver la excepción."""
    create_user(db, email="ana@example.com", nombre="Ana", password=PASSWORD)
    with TestClient(aplicacion, raise_server_exceptions=False) as c:
        datos = {"email": "ana@example.com", "password": PASSWORD}
        r = c.post("/login", data=datos, follow_redirects=False)
        assert r.status_code == 303
        yield c


def sin_detalles(r):
    texto = r.text
    for prohibido in ("Traceback", SECRETO, "RuntimeError", ".py", "File \"", "starlette"):
        assert prohibido not in texto, prohibido


# --- 404 ---


def test_404_de_pagina_muestra_la_pagina_propia(navegador):
    r = navegador.get("/esto-no-existe")
    assert r.status_code == 404
    assert "text/html" in r.headers["content-type"]
    assert "Página no encontrada" in r.text
    assert 'href="/bandeja"' in r.text
    sin_detalles(r)


def test_404_de_ticket_conserva_su_mensaje(navegador):
    r = navegador.get("/tickets/9999")
    assert r.status_code == 404
    assert "Ticket no encontrado" in r.text


def test_404_de_fichero_estatico_es_la_pagina_propia(client):
    r = client.get("/static/no-existe.css")
    assert r.status_code == 404
    assert "Página no encontrada" in r.text
    sin_detalles(r)


def test_404_publico_sin_sesion_tambien_es_la_pagina_propia(client):
    r = client.get("/login/otra-cosa")
    assert r.status_code == 404
    assert "Página no encontrada" in r.text


def test_404_de_la_api_sigue_siendo_json(navegador):
    r = navegador.get("/api/tickets/9999")
    assert r.status_code == 404
    assert r.json() == {"detail": "Ticket no encontrado"}


# --- 500 ---


def test_500_muestra_la_pagina_propia_sin_trazas(navegador):
    r = navegador.get("/health/fallo")
    assert r.status_code == 500
    assert "text/html" in r.headers["content-type"]
    assert "Algo ha salido mal" in r.text
    sin_detalles(r)


def test_500_con_sesion_tampoco_filtra_nada(navegador):
    r = navegador.get("/pagina-con-fallo")
    assert r.status_code == 500
    assert "Algo ha salido mal" in r.text
    sin_detalles(r)


def test_500_de_la_api_es_json_generico(navegador):
    r = navegador.get("/api/fallo")
    assert r.status_code == 500
    assert r.json() == {"detail": "Error interno del servidor"}
    sin_detalles(r)


def test_500_lleva_las_cabeceras_de_seguridad(navegador):
    r = navegador.get("/health/fallo")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"]
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_500_se_registra_en_el_log_del_servidor(navegador, caplog):
    navegador.get("/health/fallo")
    assert SECRETO in caplog.text


# --- 403 ---


def test_403_de_rol_es_pagina_propia(navegador):
    r = navegador.get("/admin")
    assert r.status_code == 403
    assert "Acceso denegado" in r.text
    sin_detalles(r)
