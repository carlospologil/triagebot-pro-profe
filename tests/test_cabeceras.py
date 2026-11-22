import pytest

from app.services.usuarios import create_user

PASSWORD = "una-clave-segura"


@pytest.fixture
def sesion(client, db):
    usuario = create_user(db, email="ana@example.com", nombre="Ana", password=PASSWORD)
    r = client.post(
        "/login", data={"email": usuario.email, "password": PASSWORD}, follow_redirects=False
    )
    assert r.status_code == 303
    return client


def comprobar(r):
    h = r.headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"]
    csp = h["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "'unsafe-inline'" not in csp
    assert "'unsafe-eval'" not in csp


@pytest.mark.parametrize("ruta", ["/health", "/login", "/static/estilos.css", "/no-existe"])
def test_rutas_publicas_llevan_las_cabeceras(client, ruta):
    comprobar(client.get(ruta, follow_redirects=False))


def test_redireccion_al_login_lleva_las_cabeceras(client):
    r = client.get("/bandeja", follow_redirects=False)
    assert r.status_code == 303
    comprobar(r)


@pytest.mark.parametrize(
    "ruta", ["/bandeja", "/panel", "/mi-cuenta", "/api/tickets", "/api/tickets/export.csv"]
)
def test_rutas_con_sesion_llevan_las_cabeceras(sesion, ruta):
    r = sesion.get(ruta)
    assert r.status_code == 200
    comprobar(r)


def test_las_respuestas_de_error_y_las_post_llevan_las_cabeceras(client, sesion):
    comprobar(sesion.get("/tickets/999"))
    comprobar(sesion.get("/api/tickets/999"))
    comprobar(sesion.post("/api/tickets", json={}))
    comprobar(sesion.post("/login", data={"email": "x@y.z", "password": "x"}))


def test_las_peticiones_sin_token_csrf_tambien_llevan_las_cabeceras(client):
    r = client.post("/login", data={}, headers={"X-CSRF-Token": "falso"})
    assert r.status_code == 403
    comprobar(r)


def test_la_csp_permite_el_script_de_htmx_y_nada_mas_externo(client):
    csp = client.get("/login").headers["content-security-policy"]
    assert "script-src 'self' https://unpkg.com;" in csp
    assert "style-src 'self';" in csp


def test_las_paginas_no_usan_scripts_ni_estilos_en_linea(sesion):
    for ruta in ("/bandeja", "/panel", "/mi-cuenta"):
        html = sesion.get(ruta).text
        assert " style=" not in html
        assert "<style" not in html
        assert " onclick=" not in html
        scripts = [linea for linea in html.splitlines() if "<script" in linea]
        assert all('src="https://unpkg.com/htmx.org@2.0.4"' in linea for linea in scripts)
