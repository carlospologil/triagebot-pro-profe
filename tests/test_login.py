import base64
import json

import pytest
from itsdangerous import TimestampSigner

from app.routers.sesion import MENSAJE_CREDENCIALES
from app.services.usuarios import create_user

EMAIL = "ana@example.com"
PASSWORD = "una-clave-segura"


@pytest.fixture
def usuario(db):
    return create_user(db, email=EMAIL, nombre="Ana", password=PASSWORD)


def login(client, email=EMAIL, password=PASSWORD):
    return client.post(
        "/login", data={"email": email, "password": password}, follow_redirects=False
    )


def fallar(client, veces, email=EMAIL):
    for _ in range(veces):
        assert login(client, email, "incorrecta-123").status_code == 401


# --- formulario y acceso ---


def test_get_login_muestra_formulario(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert '<form method="post" action="/login"' in r.text
    assert 'name="email"' in r.text
    assert 'name="password"' in r.text
    assert "<script" not in r.text


def test_credenciales_correctas_crean_sesion_y_redirigen_303_a_la_bandeja(client, usuario):
    r = login(client)
    assert r.status_code == 303
    assert r.headers["location"] == "/bandeja"
    page = client.get("/bandeja")
    assert page.status_code == 200
    assert "Ana" in page.text


def test_el_email_se_normaliza_al_iniciar_sesion(client, usuario):
    assert login(client, "  ANA@Example.com ").status_code == 303


def test_login_con_sesion_activa_redirige_a_la_bandeja(client, usuario):
    login(client)
    r = client.get("/login", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/bandeja"


def test_raiz_redirige_a_la_bandeja_con_sesion(client, usuario):
    login(client)
    r = client.get("/", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, "/bandeja")


# --- credenciales incorrectas ---


def test_mismo_mensaje_si_el_email_no_existe_o_la_contrasena_es_erronea(client, usuario):
    mala_clave = login(client, EMAIL, "incorrecta-123")
    sin_usuario = login(client, "nadie@example.com", PASSWORD)
    assert mala_clave.status_code == sin_usuario.status_code == 401
    assert MENSAJE_CREDENCIALES in mala_clave.text
    assert MENSAJE_CREDENCIALES in sin_usuario.text
    assert "bandeja" not in mala_clave.headers.get("location", "")


def test_fallo_de_login_no_crea_sesion(client, usuario):
    login(client, EMAIL, "incorrecta-123")
    assert client.get("/bandeja", follow_redirects=False).status_code == 303


def test_fallo_conserva_el_email_pero_nunca_la_contrasena(client, usuario):
    r = login(client, EMAIL, "incorrecta-123")
    assert f'value="{EMAIL}"' in r.text
    assert "incorrecta-123" not in r.text


def test_el_email_reflejado_se_escapa(client):
    r = login(client, '"><script>alert(1)</script>', "x")
    assert "<script>alert(1)" not in r.text


def test_usuario_inactivo_no_puede_entrar(client, usuario, db):
    db.execute("UPDATE usuarios SET activo = 0")
    db.commit()
    r = login(client)
    assert r.status_code == 401
    assert MENSAJE_CREDENCIALES in r.text


# --- rutas protegidas ---


@pytest.mark.parametrize("ruta", ["/", "/bandeja", "/logout-no-existe", "/docs", "/openapi.json"])
def test_paginas_sin_sesion_redirigen_a_login(client, ruta):
    r = client.get(ruta, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


@pytest.mark.parametrize("metodo", ["get", "post", "put", "delete"])
def test_rutas_api_sin_sesion_devuelven_401(client, metodo):
    r = getattr(client, metodo)("/api/tickets", follow_redirects=False)
    assert r.status_code == 401
    assert r.json() == {"detail": "No autenticado"}


def test_rutas_publicas_no_exigen_sesion(client):
    assert client.get("/health").status_code == 200
    assert client.get("/login").status_code == 200
    assert client.get("/static/estilos.css").status_code == 200


def test_un_prefijo_parecido_a_una_ruta_publica_no_es_publico(client):
    assert client.get("/loginx", follow_redirects=False).status_code == 303
    assert client.get("/healthz", follow_redirects=False).status_code == 303
    assert client.get("/staticfoo", follow_redirects=False).status_code == 303
    assert client.get("/apix", follow_redirects=False).status_code == 303


def test_ruta_api_con_sesion_pasa_el_control_de_acceso(client, usuario):
    login(client)
    assert client.get("/api/tickets").status_code == 404


def test_usuario_desactivado_pierde_la_sesion(client, usuario, db):
    login(client)
    db.execute("UPDATE usuarios SET activo = 0")
    db.commit()
    assert client.get("/bandeja", follow_redirects=False).status_code == 303
    assert client.get("/api/x").status_code == 401


def test_usuario_borrado_pierde_la_sesion(client, usuario, db):
    login(client)
    db.execute("DELETE FROM usuarios")
    db.commit()
    assert client.get("/bandeja", follow_redirects=False).status_code == 303


# --- logout ---


def test_logout_cierra_la_sesion_y_redirige_a_login(client, usuario):
    login(client)
    r = client.post("/logout", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
    assert client.get("/bandeja", follow_redirects=False).status_code == 303


def test_logout_solo_acepta_post(client, usuario):
    login(client)
    assert client.get("/logout", follow_redirects=False).status_code == 405
    assert client.get("/bandeja").status_code == 200


def test_logout_sin_sesion_redirige_a_login(client):
    r = client.post("/logout", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, "/login")


# --- cookie de sesión ---


def test_cookie_de_sesion_httponly_y_samesite_lax(client, usuario):
    cabecera = login(client).headers["set-cookie"].lower()
    assert cabecera.startswith("session=")
    assert "httponly" in cabecera
    assert "samesite=lax" in cabecera


def _cookie_firmada(clave: str, datos: dict) -> str:
    cuerpo = base64.b64encode(json.dumps(datos).encode("utf-8"))
    return TimestampSigner(clave).sign(cuerpo).decode("utf-8")


def test_la_cookie_esta_firmada_con_secret_key(client, usuario, settings):
    login(client)
    valor = client.cookies.get("session")
    firmado = TimestampSigner(settings.secret_key).unsign(valor.encode("utf-8"))
    assert json.loads(base64.b64decode(firmado)) == {"usuario_id": usuario.id}


def test_cookie_firmada_con_la_clave_correcta_es_aceptada(client, usuario, settings):
    client.cookies.set("session", _cookie_firmada(settings.secret_key, {"usuario_id": usuario.id}))
    assert client.get("/bandeja").status_code == 200


def test_cookie_firmada_con_otra_clave_es_rechazada(client, usuario):
    client.cookies.set("session", _cookie_firmada("otra-clave", {"usuario_id": usuario.id}))
    assert client.get("/bandeja", follow_redirects=False).status_code == 303


def test_cookie_manipulada_es_rechazada(client, usuario):
    login(client)
    valor = client.cookies.get("session")
    cuerpo, _, firma = valor.rpartition(".")
    client.cookies.clear()
    client.cookies.set("session", f"{cuerpo}.{firma[:-2]}AA")
    assert client.get("/bandeja", follow_redirects=False).status_code == 303


# --- bloqueo por intentos fallidos ---


def test_cinco_fallos_seguidos_bloquean_aunque_luego_acierte(client, usuario, reloj):
    fallar(client, 5)
    r = login(client)
    assert r.status_code == 401
    assert MENSAJE_CREDENCIALES in r.text
    assert client.get("/bandeja", follow_redirects=False).status_code == 303


def test_cuatro_fallos_no_bloquean(client, usuario):
    fallar(client, 4)
    assert login(client).status_code == 303


def test_un_acierto_reinicia_el_contador(client, usuario):
    fallar(client, 4)
    assert login(client).status_code == 303
    client.post("/logout")
    fallar(client, 4)
    assert login(client).status_code == 303


def test_el_bloqueo_dura_15_minutos(client, usuario, reloj):
    fallar(client, 5)
    reloj.avanzar(minutes=14, seconds=59)
    assert login(client).status_code == 401
    reloj.avanzar(seconds=1)
    assert login(client).status_code == 303


def test_intentos_durante_el_bloqueo_no_lo_prolongan(client, usuario, reloj):
    fallar(client, 5)
    reloj.avanzar(minutes=10)
    fallar(client, 3)
    reloj.avanzar(minutes=5)
    assert login(client).status_code == 303


def test_tras_el_bloqueo_el_contador_empieza_de_cero(client, usuario, reloj):
    fallar(client, 5)
    reloj.avanzar(minutes=15)
    fallar(client, 4)
    assert login(client).status_code == 303


def test_el_bloqueo_es_por_usuario(client, usuario, db):
    create_user(db, email="luis@example.com", nombre="Luis", password=PASSWORD)
    fallar(client, 5)
    assert login(client, "luis@example.com").status_code == 303


def test_el_bloqueo_se_guarda_en_base_de_datos(client, usuario, db, reloj):
    fallar(client, 5)
    fila = db.execute("SELECT intentos_fallidos, bloqueado_hasta FROM usuarios").fetchone()
    assert fila["bloqueado_hasta"] == "2026-03-02T09:15:00Z"
    assert fila["intentos_fallidos"] == 0


def test_fallos_con_email_inexistente_no_crean_usuarios_ni_fallan(client, db):
    fallar(client, 6, email="fantasma@example.com")
    assert db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0
