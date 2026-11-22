import re
from pathlib import Path

import pytest

from app.services import demo
from app.services.usuarios import create_user

PASSWORD = "una-clave-segura"
NUEVA = "otra-clave-distinta"
CSS = Path(__file__).parent.parent / "app" / "static" / "acabado.css"

ENLACES_COMUNES = ("/bandeja", "/panel")
ENLACES_ADMIN = ("/admin/usuarios", "/admin/auditoria", "/admin")
PAGINAS_COMUNES = ("/bandeja", "/panel", "/mi-cuenta")
PAGINAS_ADMIN = ("/admin", "/admin/usuarios", "/admin/auditoria")


def entrar(client, email, password=PASSWORD):
    r = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
    assert r.status_code == 303
    return client


@pytest.fixture
def agente(db):
    return create_user(db, email="agente@example.com", nombre="Ana Agente", password=PASSWORD)


@pytest.fixture
def admin(db):
    return create_user(
        db, email="admin@example.com", nombre="Root Admin", password=PASSWORD, rol="admin"
    )


@pytest.fixture
def ticket_id(db, reloj):
    demo.crear_datos_demo(db, reloj)
    return db.execute("SELECT id FROM tickets ORDER BY id LIMIT 1").fetchone()[0]


def enlaces(html):
    return set(re.findall(r'<nav class="navegacion"[^>]*>(.*?)</nav>', html, re.S)[0].split('"'))


def comprobar_barra(html, nombre):
    assert 'class="barra"' in html
    assert "TriageBot" in html
    assert '<nav class="navegacion" aria-label="Principal">' in html
    assert nombre in html
    assert 'action="/logout"' in html
    assert "Cerrar sesión" in html


@pytest.mark.parametrize("ruta", PAGINAS_COMUNES)
def test_paginas_principales_del_agente(client, agente, ruta):
    entrar(client, agente.email)
    r = client.get(ruta)
    assert r.status_code == 200
    comprobar_barra(r.text, "Ana Agente")
    barra = enlaces(r.text)
    for enlace in ENLACES_COMUNES:
        assert enlace in barra
    for enlace in ENLACES_ADMIN:
        assert enlace not in barra


@pytest.mark.parametrize("ruta", PAGINAS_COMUNES + PAGINAS_ADMIN)
def test_paginas_principales_del_admin(client, admin, ruta):
    entrar(client, admin.email)
    r = client.get(ruta)
    assert r.status_code == 200
    comprobar_barra(r.text, "Root Admin")
    barra = enlaces(r.text)
    for enlace in ENLACES_COMUNES + ENLACES_ADMIN:
        assert enlace in barra


def test_detalle_de_ticket_tiene_la_navegacion(client, agente, ticket_id):
    entrar(client, agente.email)
    r = client.get(f"/tickets/{ticket_id}")
    assert r.status_code == 200
    comprobar_barra(r.text, "Ana Agente")
    assert "/panel" in enlaces(r.text)


def test_la_pagina_actual_se_marca_en_la_navegacion(client, agente):
    entrar(client, agente.email)
    html = client.get("/panel").text
    assert re.search(r'<a href="/panel" aria-current="page">Panel</a>', html)
    assert 'href="/bandeja" aria-current' not in html


def test_login_no_muestra_la_navegacion(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert "TriageBot" in r.text
    assert 'class="navegacion"' not in r.text


def test_cerrar_sesion_muestra_un_mensaje(client, agente):
    entrar(client, agente.email)
    r = client.post("/logout", follow_redirects=True)
    assert r.status_code == 200
    assert "Has cerrado sesión." in r.text
    assert "mensaje-ok" in r.text
    assert "Has cerrado sesión." not in client.get("/login").text


def test_login_incorrecto_muestra_mensaje_de_error(client, agente):
    r = client.post("/login", data={"email": agente.email, "password": "mala"})
    assert r.status_code == 401
    assert 'class="mensaje mensaje-error"' in r.text
    assert 'role="alert"' in r.text


def test_acciones_del_detalle_confirman_con_mensaje(client, agente, ticket_id):
    entrar(client, agente.email)
    r = client.post(
        f"/tickets/{ticket_id}/estado", data={"estado": "en_curso"}, follow_redirects=True
    )
    assert r.status_code == 200
    assert "mensaje-ok" in r.text


def test_error_de_estado_invalido_se_muestra_como_mensaje(client, agente, ticket_id):
    entrar(client, agente.email)
    r = client.post(
        f"/tickets/{ticket_id}/estado", data={"estado": "inventado"}, follow_redirects=True
    )
    assert "mensaje-error" in r.text


def test_cambiar_contrasena_confirma_con_mensaje(client, agente):
    entrar(client, agente.email)
    r = client.post(
        "/mi-cuenta/password",
        data={"actual": PASSWORD, "nueva": NUEVA, "confirmacion": NUEVA},
        follow_redirects=True,
    )
    assert "Contraseña actualizada." in r.text
    assert "mensaje-ok" in r.text


def test_error_de_contrasena_aparece_junto_al_campo(client, agente):
    entrar(client, agente.email)
    r = client.post(
        "/mi-cuenta/password",
        data={"actual": "incorrecta", "nueva": NUEVA, "confirmacion": NUEVA},
    )
    assert r.status_code >= 400
    assert "mensaje-error" in r.text
    assert re.search(r'id="actual"[^>]*aria-invalid="true"', r.text)
    assert 'class="error-campo"' in r.text


def test_confirmacion_distinta_marca_el_campo_de_confirmacion(client, agente):
    entrar(client, agente.email)
    r = client.post(
        "/mi-cuenta/password",
        data={"actual": PASSWORD, "nueva": "otra-clave-distinta", "confirmacion": "no-coincide-1"},
    )
    assert re.search(r'id="confirmacion"[^>]*aria-invalid="true"', r.text)


def test_alta_de_usuario_con_email_duplicado_marca_el_campo(client, admin, agente):
    entrar(client, admin.email)
    r = client.post(
        "/admin/usuarios",
        data={"email": agente.email, "nombre": "Otra", "rol": "agente", "password": ""},
    )
    assert r.status_code == 409
    assert re.search(r'id="nuevo-email"[^>]*aria-invalid="true"', r.text)
    assert 'id="error-nuevo-email"' in r.text
    assert "mensaje-error" in r.text


def test_alta_de_usuario_correcta_confirma_con_mensaje(client, admin):
    entrar(client, admin.email)
    r = client.post(
        "/admin/usuarios",
        data={"email": "nuevo@example.com", "nombre": "Nuevo", "rol": "agente", "password": ""},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "nuevo@example.com" in r.text
    assert "mensaje-ok" in r.text


@pytest.mark.parametrize("ruta", ("/mi-cuenta", "/admin/usuarios"))
def test_todos_los_campos_de_texto_tienen_etiqueta(client, admin, ruta):
    entrar(client, admin.email)
    html = client.get(ruta).text
    formularios = re.findall(r"<form.*?</form>", html, re.S)
    assert formularios
    for formulario in formularios:
        for campo in re.findall(r"<(?:input|select|textarea)\b[^>]*>", formulario):
            if 'type="hidden"' in campo or 'type="submit"' in campo:
                continue
            if "aria-label=" in campo:
                continue
            identificador = re.search(r'\bid="([^"]+)"', campo)
            assert identificador, campo
            assert f'for="{identificador.group(1)}"' in html, campo


def test_los_paneles_del_detalle_etiquetan_sus_selectores(client, agente, ticket_id):
    entrar(client, agente.email)
    html = client.get(f"/tickets/{ticket_id}").text
    for campo in re.findall(r"<(?:select|textarea)\b[^>]*>", html):
        identificador = re.search(r'\bid="([^"]+)"', campo)
        assert identificador, campo
        assert f'for="{identificador.group(1)}"' in html, campo


def test_el_html_declara_viewport_y_enlaza_el_css_de_acabado(client, agente):
    entrar(client, agente.email)
    html = client.get("/bandeja").text
    assert 'name="viewport"' in html
    assert "width=device-width" in html
    assert "/static/acabado.css" in html
    assert 'class="saltar"' in html
    assert client.get("/static/acabado.css").status_code == 200


def test_el_css_tiene_foco_visible_y_diseno_movil():
    css = CSS.read_text(encoding="utf-8")
    assert ":focus-visible" in css
    assert "outline: 3px" in css
    assert re.search(r"@media \(max-width: 40rem\)", css)
    assert ".tabla-tickets" in css
    assert "min-height: 2.75rem" in css


def test_ninguna_pagina_se_queda_sin_etiqueta_de_idioma(client, agente):
    entrar(client, agente.email)
    assert '<html lang="es">' in client.get("/bandeja").text
