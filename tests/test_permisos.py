from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.main import create_app
from app.permisos import MENSAJE_PROHIBIDO, require_role
from app.routers.sesion import MENSAJE_CREDENCIALES
from app.services.usuarios import Usuario, create_user

PASSWORD = "una-clave-segura"


@pytest.fixture
def admin(db):
    return create_user(db, email="admin@example.com", nombre="Alba", password=PASSWORD, rol="admin")


@pytest.fixture
def agente(db):
    return create_user(db, email="agente@example.com", nombre="Ana", password=PASSWORD)


def login(client, usuario):
    r = client.post(
        "/login", data={"email": usuario.email, "password": PASSWORD}, follow_redirects=False
    )
    assert r.status_code == 303
    return r


def desactivar(db, usuario):
    db.execute("UPDATE usuarios SET activo = 0 WHERE id = ?", (usuario.id,))
    db.commit()


@pytest.fixture
def client_rutas(settings, reloj):
    """App con rutas de prueba protegidas con require_role para comprobar la dependencia."""
    application = create_app(settings, clock=reloj)

    @application.get("/api/solo-admin")
    def solo_admin(usuario: Annotated[Usuario, Depends(require_role("admin"))]):
        return {"rol": usuario.rol}

    @application.get("/api/solo-agente")
    def solo_agente(usuario: Annotated[Usuario, Depends(require_role("agente"))]):
        return {"rol": usuario.rol}

    @application.get("/api/ambos")
    def ambos(usuario: Annotated[Usuario, Depends(require_role("admin", "agente"))]):
        return {"rol": usuario.rol}

    with TestClient(application) as test_client:
        yield test_client


# --- /admin: acceso permitido y denegado ---


def test_admin_accede_a_admin(client, admin):
    login(client, admin)
    r = client.get("/admin")
    assert r.status_code == 200
    assert "Administración" in r.text


def test_agente_recibe_403_en_admin(client, agente):
    login(client, agente)
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 403
    assert MENSAJE_PROHIBIDO in r.text
    assert "Acceso denegado" in r.text


def test_sin_sesion_admin_redirige_a_login(client):
    r = client.get("/admin", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, "/login")


def test_el_enlace_a_administracion_solo_se_muestra_al_admin(client, admin, agente):
    login(client, agente)
    assert 'href="/admin"' not in client.get("/bandeja").text
    client.post("/logout")
    login(client, admin)
    assert 'href="/admin"' in client.get("/bandeja").text


def test_los_roles_no_cambian_el_acceso_a_la_bandeja(client, admin, agente):
    for usuario in (admin, agente):
        login(client, usuario)
        assert client.get("/bandeja").status_code == 200
        client.post("/logout")


# --- require_role ---


def test_require_role_permite_el_rol_indicado_y_devuelve_el_usuario(client_rutas, admin):
    login(client_rutas, admin)
    r = client_rutas.get("/api/solo-admin")
    assert (r.status_code, r.json()) == (200, {"rol": "admin"})


def test_require_role_deniega_otro_rol_con_403_json_en_api(client_rutas, agente):
    login(client_rutas, agente)
    r = client_rutas.get("/api/solo-admin")
    assert r.status_code == 403
    assert r.json() == {"detail": MENSAJE_PROHIBIDO}


def test_require_role_para_agente_deniega_al_admin(client_rutas, admin, agente):
    login(client_rutas, agente)
    assert client_rutas.get("/api/solo-agente").status_code == 200
    client_rutas.post("/logout")
    login(client_rutas, admin)
    assert client_rutas.get("/api/solo-agente").status_code == 403


def test_require_role_admite_varios_roles(client_rutas, admin, agente):
    for usuario in (admin, agente):
        login(client_rutas, usuario)
        assert client_rutas.get("/api/ambos").json() == {"rol": usuario.rol}
        client_rutas.post("/logout")


def test_require_role_sin_roles_o_con_rol_desconocido_falla():
    with pytest.raises(ValueError):
        require_role()
    with pytest.raises(ValueError, match="superusuario"):
        require_role("superusuario")


# --- usuario desactivado ---


def test_usuario_desactivado_no_puede_iniciar_sesion(client, agente, db):
    desactivar(db, agente)
    r = client.post(
        "/login", data={"email": agente.email, "password": PASSWORD}, follow_redirects=False
    )
    assert r.status_code == 401
    assert MENSAJE_CREDENCIALES in r.text
    assert client.get("/bandeja", follow_redirects=False).status_code == 303


def test_admin_desactivado_no_puede_iniciar_sesion(client, admin, db):
    desactivar(db, admin)
    r = client.post(
        "/login", data={"email": admin.email, "password": PASSWORD}, follow_redirects=False
    )
    assert r.status_code == 401
    assert client.get("/admin", follow_redirects=False).status_code == 303


def test_agente_desactivado_con_sesion_abierta_es_expulsado_a_login(client, agente, db):
    login(client, agente)
    assert client.get("/bandeja").status_code == 200
    desactivar(db, agente)
    r = client.get("/bandeja", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, "/login")


def test_admin_desactivado_con_sesion_abierta_es_expulsado_de_admin(client, admin, db):
    login(client, admin)
    assert client.get("/admin").status_code == 200
    desactivar(db, admin)
    r = client.get("/admin", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, "/login")


def test_la_expulsion_destruye_la_sesion(client, agente, db):
    login(client, agente)
    desactivar(db, agente)
    client.get("/bandeja", follow_redirects=False)
    db.execute("UPDATE usuarios SET activo = 1")
    db.commit()
    assert client.get("/bandeja", follow_redirects=False).status_code == 303


def test_desactivado_con_sesion_no_pasa_por_require_role(client_rutas, admin, db):
    login(client_rutas, admin)
    desactivar(db, admin)
    r = client_rutas.get("/api/solo-admin")
    assert r.status_code == 401


def test_un_cambio_de_rol_se_aplica_en_la_siguiente_peticion(client, admin, db):
    login(client, admin)
    assert client.get("/admin").status_code == 200
    db.execute("UPDATE usuarios SET rol = 'agente' WHERE id = ?", (admin.id,))
    db.commit()
    assert client.get("/admin").status_code == 403
