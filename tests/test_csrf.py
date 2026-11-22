import re

import pytest
from fastapi.testclient import TestClient

from app.services.usuarios import create_user

pytestmark = pytest.mark.csrf_estricto

PASSWORD = "una-clave-segura"
CAMPO = re.compile(r'name="csrf_token" value="([^"]+)"')
CABECERA = re.compile(r'hx-headers=\'\{"X-CSRF-Token": "([^"]+)"\}\'')


@pytest.fixture
def agente(db):
    return create_user(db, email="agente@example.com", nombre="Ana", password=PASSWORD)


@pytest.fixture
def admin(db):
    return create_user(db, email="admin@example.com", nombre="Root", password=PASSWORD, rol="admin")


@pytest.fixture
def ticket(db):
    cursor = db.execute(
        "INSERT INTO tickets (asunto, descripcion, solicitante_nombre, solicitante_email, "
        "estado, prioridad, categoria, creado_en, actualizado_en) VALUES ('Asunto', 'Texto', "
        "'Marta', 'marta@example.com', 'nuevo', 'media', 'otro', "
        "'2026-03-02T06:30:00Z', '2026-03-02T06:30:00Z')"
    )
    db.commit()
    return cursor.lastrowid


def token_de(html: str) -> str:
    return CAMPO.search(html).group(1)


def entrar(client, usuario) -> str:
    """Inicia sesión como un navegador (con el token del formulario) y devuelve el token nuevo."""
    token = token_de(client.get("/login").text)
    r = client.post(
        "/login",
        data={"email": usuario.email, "password": PASSWORD, "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303
    return token_de(client.get("/bandeja").text)


def estado_de(db, ticket_id):
    return db.execute("SELECT estado FROM tickets WHERE id = ?", (ticket_id,)).fetchone()[0]


# --- el formulario de login ---


def test_login_sin_token_se_rechaza_con_403(client, agente):
    r = client.post(
        "/login", data={"email": agente.email, "password": PASSWORD}, follow_redirects=False
    )
    assert r.status_code == 403


def test_login_sin_token_no_abre_sesion(client, agente):
    client.post("/login", data={"email": agente.email, "password": PASSWORD})
    assert client.get("/bandeja", follow_redirects=False).status_code == 303


def test_login_con_token_falso_se_rechaza(client, agente):
    client.get("/login")
    r = client.post(
        "/login",
        data={"email": agente.email, "password": PASSWORD, "csrf_token": "falso"},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_login_con_el_token_del_formulario_funciona(client, agente):
    token = token_de(client.get("/login").text)
    r = client.post(
        "/login",
        data={"email": agente.email, "password": PASSWORD, "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/bandeja"


def test_el_token_cambia_al_iniciar_sesion(client, agente):
    antes = token_de(client.get("/login").text)
    despues = entrar(client, agente)
    assert antes != despues


def test_el_403_es_una_pagina_propia_y_no_filtra_detalles(client):
    r = client.post("/login", data={"email": "a@b.c", "password": "x"})
    assert r.status_code == 403
    assert "text/html" in r.headers["content-type"]
    assert "Acceso denegado" in r.text
    assert "Traceback" not in r.text


# --- acciones con sesión ---


def test_logout_sin_token_no_cierra_la_sesion(client, agente):
    entrar(client, agente)
    assert client.post("/logout", follow_redirects=False).status_code == 403
    assert client.get("/bandeja", follow_redirects=False).status_code == 200


def test_logout_con_token_cierra_la_sesion(client, agente):
    token = entrar(client, agente)
    r = client.post("/logout", data={"csrf_token": token}, follow_redirects=False)
    assert r.status_code == 303
    assert client.get("/bandeja", follow_redirects=False).status_code == 303


def test_cambiar_estado_sin_token_responde_403_y_no_cambia_nada(client, agente, ticket, db):
    entrar(client, agente)
    r = client.post(f"/tickets/{ticket}/estado", data={"estado": "en_curso"})
    assert r.status_code == 403
    assert estado_de(db, ticket) == "nuevo"


def test_cambiar_estado_con_token_de_formulario(client, agente, ticket, db):
    token = entrar(client, agente)
    r = client.post(
        f"/tickets/{ticket}/estado",
        data={"estado": "en_curso", "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert estado_de(db, ticket) == "en_curso"


def test_peticion_htmx_con_cabecera_csrf(client, agente, ticket, db):
    token = entrar(client, agente)
    cabeceras = {"HX-Request": "true", "X-CSRF-Token": token}
    r = client.post(f"/tickets/{ticket}/estado", data={"estado": "en_curso"}, headers=cabeceras)
    assert r.status_code == 200
    assert estado_de(db, ticket) == "en_curso"


def test_peticion_htmx_sin_cabecera_csrf_es_403(client, agente, ticket, db):
    entrar(client, agente)
    r = client.post(
        f"/tickets/{ticket}/estado", data={"estado": "en_curso"}, headers={"HX-Request": "true"}
    )
    assert r.status_code == 403
    assert estado_de(db, ticket) == "nuevo"


def test_token_de_otra_sesion_no_vale(client, agente, ticket, db):
    entrar(client, agente)
    ajeno = token_de(TestClient(client.app).get("/login").text)
    r = client.post(f"/tickets/{ticket}/estado", data={"estado": "en_curso", "csrf_token": ajeno})
    assert r.status_code == 403
    assert estado_de(db, ticket) == "nuevo"


def test_la_cabecera_tiene_prioridad_sobre_un_campo_falso(client, agente, ticket):
    token = entrar(client, agente)
    r = client.post(
        f"/tickets/{ticket}/estado",
        data={"estado": "en_curso", "csrf_token": "falso"},
        headers={"X-CSRF-Token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303


@pytest.mark.parametrize(
    "ruta",
    ["/mi-cuenta/password", "/admin/usuarios", "/admin/usuarios/1/desactivar"],
)
def test_otras_rutas_post_exigen_token(client, admin, ruta):
    entrar(client, admin)
    assert client.post(ruta, data={"nueva": "x"}).status_code == 403


def test_cambiar_password_sin_token_no_la_cambia(client, agente, db):
    entrar(client, agente)
    antes = db.execute("SELECT password_hash FROM usuarios").fetchone()[0]
    client.post(
        "/mi-cuenta/password",
        data={"actual": PASSWORD, "nueva": "otra-clave-larga", "confirmacion": "otra-clave-larga"},
    )
    assert db.execute("SELECT password_hash FROM usuarios").fetchone()[0] == antes


def test_los_get_no_necesitan_token(client, agente):
    assert client.get("/login").status_code == 200
    entrar(client, agente)
    assert client.get("/bandeja").status_code == 200
    assert client.get("/health").status_code == 200


# --- API JSON ---

TICKET_API = {
    "asunto": "Fallo",
    "texto": "No funciona",
    "email_cliente": "c@example.com",
    "nombre_cliente": "Cris",
}


def test_la_api_sin_token_responde_403_en_json(client, agente, db):
    entrar(client, agente)
    r = client.post("/api/tickets", json=TICKET_API)
    assert r.status_code == 403
    assert r.headers["content-type"].startswith("application/json")
    assert db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 0


def test_la_api_acepta_la_cabecera_csrf(client, agente):
    token = entrar(client, agente)
    r = client.post("/api/tickets", json=TICKET_API, headers={"X-CSRF-Token": token})
    assert r.status_code == 201


def test_patch_y_reclasificar_exigen_token(client, agente, ticket):
    entrar(client, agente)
    assert client.patch(f"/api/tickets/{ticket}", json={"estado": "en_curso"}).status_code == 403
    assert client.post(f"/api/tickets/{ticket}/reclasificar").status_code == 403


# --- los formularios llevan el token ---


def test_todas_las_paginas_incluyen_token_en_cada_formulario_post(client, admin, ticket):
    token = entrar(client, admin)
    rutas = [
        "/bandeja",
        "/panel",
        "/mi-cuenta",
        "/admin",
        "/admin/usuarios",
        "/admin/auditoria",
        f"/tickets/{ticket}",
    ]
    for ruta in rutas:
        html = client.get(ruta).text
        formularios = re.findall(r"<form\b[^>]*method=\"post\"[^>]*>(.*?)</form>", html, re.S)
        assert formularios, ruta
        for cuerpo in formularios:
            assert f'name="csrf_token" value="{token}"' in cuerpo, ruta


def test_la_plantilla_base_configura_htmx_con_la_cabecera_csrf(client, admin, ticket):
    token = entrar(client, admin)
    for ruta in ("/bandeja", f"/tickets/{ticket}"):
        html = client.get(ruta).text
        assert CABECERA.search(html).group(1) == token
        assert f'<meta name="csrf-token" content="{token}">' in html


def test_los_paneles_htmx_devueltos_tambien_llevan_el_token(client, agente, ticket):
    token = entrar(client, agente)
    r = client.post(
        f"/tickets/{ticket}/estado",
        data={"estado": "nuevo"},
        headers={"HX-Request": "true", "X-CSRF-Token": token},
    )
    assert f'name="csrf_token" value="{token}"' in r.text


def test_la_configuracion_de_htmx_del_detalle_conserva_el_manejo_de_errores(
    client, agente, ticket
):
    entrar(client, agente)
    html = client.get(f"/tickets/{ticket}").text
    assert html.count('name="htmx-config"') == 1
    assert "responseHandling" in html
