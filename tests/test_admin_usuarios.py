import pytest

from app.auth import verify_password
from app.services import auditoria
from app.services import usuarios as servicio
from app.services.usuarios import create_user, get_user, get_user_by_email

PASSWORD = "una-clave-segura"
BASE = "/admin/usuarios"


@pytest.fixture
def admin(db):
    return create_user(db, email="admin@example.com", nombre="Root", password=PASSWORD, rol="admin")


@pytest.fixture
def otro_admin(db):
    return create_user(db, email="otro@example.com", nombre="Otro", password=PASSWORD, rol="admin")


@pytest.fixture
def agente(db):
    return create_user(db, email="agente@example.com", nombre="Ana", password=PASSWORD)


def entrar(client, usuario, password=PASSWORD):
    r = client.post(
        "/login", data={"email": usuario.email, "password": password}, follow_redirects=False
    )
    assert r.status_code == 303


@pytest.fixture
def sesion_admin(client, admin):
    entrar(client, admin)
    return client


def acciones(db, accion):
    return db.execute("SELECT * FROM auditoria WHERE accion = ? ORDER BY id", (accion,)).fetchall()


def post(client, ruta, **datos):
    return client.post(ruta, data=datos, follow_redirects=False)


# --- Acceso y listado -------------------------------------------------------------------------


def test_listado_requiere_sesion(client):
    r = client.get(BASE, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_agente_no_puede_gestionar_usuarios(client, agente, otro_admin):
    entrar(client, agente)
    assert client.get(BASE).status_code == 403
    assert post(client, BASE, email="x@example.com", nombre="X").status_code == 403
    assert post(client, f"{BASE}/{otro_admin.id}/desactivar").status_code == 403
    assert post(client, f"{BASE}/{otro_admin.id}/rol", rol="agente").status_code == 403
    assert post(client, f"{BASE}/{otro_admin.id}/restablecer").status_code == 403


def test_listado_muestra_activos_e_inactivos(sesion_admin, db, admin, agente):
    servicio.desactivar(db, agente.id, actor_id=admin.id)
    r = sesion_admin.get(BASE)
    assert r.status_code == 200
    assert "admin@example.com" in r.text
    assert "agente@example.com" in r.text
    assert "Inactivo" in r.text
    assert "Reactivar" in r.text


def test_el_propio_admin_no_tiene_boton_de_desactivar(sesion_admin, admin):
    r = sesion_admin.get(BASE)
    assert f"{BASE}/{admin.id}/desactivar" not in r.text


# --- Crear ------------------------------------------------------------------------------------


def test_crear_usuario_con_contrasena_indicada(sesion_admin, db, admin):
    r = post(
        sesion_admin,
        BASE,
        email=" Nuevo@Example.com ",
        nombre="Nuria",
        rol="agente",
        password="clave-inicial-1",
    )
    assert r.status_code == 303
    nuevo = get_user_by_email(db, "nuevo@example.com")
    assert nuevo.rol == "agente"
    assert nuevo.activo
    assert nuevo.debe_cambiar_password
    fila = acciones(db, auditoria.USUARIO_CREADO)[-1]
    assert fila["usuario_id"] == admin.id
    assert "nuevo@example.com" in fila["valor_nuevo"]
    assert "nuevo@example.com" in sesion_admin.get(BASE).text


def test_crear_usuario_sin_contrasena_genera_una_temporal_que_se_muestra_una_vez(sesion_admin, db):
    r = post(sesion_admin, BASE, email="nuevo@example.com", nombre="Nuria", rol="admin")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert "Contraseña temporal" in r.text
    row = db.execute("SELECT * FROM usuarios WHERE email = 'nuevo@example.com'").fetchone()
    assert row["rol"] == "admin"
    assert row["debe_cambiar_password"] == 1
    temporal = r.text.split('class="password-temporal">')[1].split("<")[0]
    assert verify_password(temporal, row["password_hash"])
    assert temporal not in sesion_admin.get(BASE).text


@pytest.mark.parametrize(
    ("datos", "status"),
    [
        ({"email": "no-es-email", "nombre": "X", "rol": "agente"}, 422),
        ({"email": "x@example.com", "nombre": "  ", "rol": "agente"}, 422),
        ({"email": "x@example.com", "nombre": "X", "rol": "superman"}, 422),
        ({"email": "x@example.com", "nombre": "X", "rol": "agente", "password": "corta"}, 422),
        ({"email": "agente@example.com", "nombre": "X", "rol": "agente"}, 409),
    ],
)
def test_crear_usuario_invalido_se_rechaza(sesion_admin, db, agente, datos, status):
    antes = db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
    r = post(sesion_admin, BASE, **datos)
    assert r.status_code == status
    assert 'role="alert"' in r.text
    assert db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == antes


# --- Cambiar rol ------------------------------------------------------------------------------


def test_cambiar_rol(sesion_admin, db, admin, agente):
    r = post(sesion_admin, f"{BASE}/{agente.id}/rol", rol="admin")
    assert r.status_code == 303
    assert get_user(db, agente.id).rol == "admin"
    fila = acciones(db, auditoria.USUARIO_ROL_CAMBIADO)[-1]
    assert (fila["usuario_id"], fila["valor_anterior"], fila["valor_nuevo"]) == (
        admin.id,
        "agente",
        "admin",
    )


def test_cambiar_rol_a_rol_invalido(sesion_admin, db, agente):
    r = post(sesion_admin, f"{BASE}/{agente.id}/rol", rol="superman")
    assert r.status_code == 422
    assert get_user(db, agente.id).rol == "agente"


def test_un_admin_puede_quitarse_el_rol_si_hay_otro_admin_activo(
    sesion_admin, db, admin, otro_admin
):
    r = post(sesion_admin, f"{BASE}/{admin.id}/rol", rol="agente")
    assert r.status_code == 303
    assert get_user(db, admin.id).rol == "agente"


def test_no_se_puede_quitar_el_rol_al_ultimo_admin_activo(sesion_admin, db, admin):
    r = post(sesion_admin, f"{BASE}/{admin.id}/rol", rol="agente")
    assert r.status_code == 409
    assert "último administrador activo" in r.text
    assert get_user(db, admin.id).rol == "admin"
    assert acciones(db, auditoria.USUARIO_ROL_CAMBIADO) == []


def test_un_admin_inactivo_no_cuenta_como_admin_activo(sesion_admin, db, admin, otro_admin):
    servicio.desactivar(db, otro_admin.id, actor_id=admin.id)
    r = post(sesion_admin, f"{BASE}/{admin.id}/rol", rol="agente")
    assert r.status_code == 409
    assert get_user(db, admin.id).rol == "admin"


def test_servicio_proteccion_ultimo_admin(db, admin, agente):
    with pytest.raises(servicio.ProteccionError):
        servicio.cambiar_rol(db, admin.id, "agente", actor_id=agente.id)
    with pytest.raises(servicio.ProteccionError):
        servicio.desactivar(db, admin.id, actor_id=agente.id)
    assert get_user(db, admin.id).rol == "admin"
    assert get_user(db, admin.id).activo


# --- Desactivar y reactivar -------------------------------------------------------------------


def test_desactivar_impide_iniciar_sesion_y_cierra_la_sesion_abierta(
    sesion_admin, client, db, admin, agente
):
    from fastapi.testclient import TestClient

    otro_cliente = TestClient(client.app)
    entrar(otro_cliente, agente)
    assert otro_cliente.get("/bandeja").status_code == 200

    r = post(sesion_admin, f"{BASE}/{agente.id}/desactivar")
    assert r.status_code == 303
    assert not get_user(db, agente.id).activo
    fila = acciones(db, auditoria.USUARIO_DESACTIVADO)[-1]
    assert (fila["usuario_id"], fila["detalle"]) == (admin.id, agente.email)

    assert otro_cliente.get("/bandeja", follow_redirects=False).status_code == 303
    r = otro_cliente.post(
        "/login", data={"email": agente.email, "password": PASSWORD}, follow_redirects=False
    )
    assert r.status_code == 401


def test_reactivar_permite_volver_a_entrar(sesion_admin, client, db, admin, agente):
    servicio.desactivar(db, agente.id, actor_id=admin.id)
    r = post(sesion_admin, f"{BASE}/{agente.id}/reactivar")
    assert r.status_code == 303
    assert get_user(db, agente.id).activo
    assert acciones(db, auditoria.USUARIO_REACTIVADO)[-1]["detalle"] == agente.email

    from fastapi.testclient import TestClient

    otro_cliente = TestClient(client.app)
    entrar(otro_cliente, agente)


def test_desactivar_dos_veces_no_duplica_la_auditoria(db, admin, agente):
    servicio.desactivar(db, agente.id, actor_id=admin.id)
    servicio.desactivar(db, agente.id, actor_id=admin.id)
    assert len(acciones(db, auditoria.USUARIO_DESACTIVADO)) == 1


def test_un_admin_no_puede_desactivarse_a_si_mismo(sesion_admin, db, admin, otro_admin):
    r = post(sesion_admin, f"{BASE}/{admin.id}/desactivar")
    assert r.status_code == 409
    assert "tu propia cuenta" in r.text
    assert get_user(db, admin.id).activo
    assert acciones(db, auditoria.USUARIO_DESACTIVADO) == []


def test_servicio_autodesactivacion(db, admin, otro_admin):
    with pytest.raises(servicio.ProteccionError):
        servicio.desactivar(db, admin.id, actor_id=admin.id)
    assert get_user(db, admin.id).activo


def test_no_se_puede_desactivar_al_ultimo_admin_activo(db, admin, otro_admin):
    servicio.desactivar(db, otro_admin.id, actor_id=admin.id)
    with pytest.raises(servicio.ProteccionError, match="último administrador"):
        servicio.desactivar(db, admin.id, actor_id=otro_admin.id)
    assert get_user(db, admin.id).activo


# --- Restablecer contraseña -------------------------------------------------------------------


def test_restablecer_muestra_temporal_una_vez_y_obliga_a_cambiarla(
    sesion_admin, client, db, admin, agente
):
    r = post(sesion_admin, f"{BASE}/{agente.id}/restablecer")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    temporal = r.text.split('class="password-temporal">')[1].split("<")[0]
    assert len(temporal) >= 10
    assert agente.email in r.text

    row = db.execute("SELECT * FROM usuarios WHERE id = ?", (agente.id,)).fetchone()
    assert row["debe_cambiar_password"] == 1
    assert verify_password(temporal, row["password_hash"])
    assert not verify_password(PASSWORD, row["password_hash"])
    assert temporal not in str(dict(acciones(db, auditoria.PASSWORD_RESTABLECIDA)[-1]))

    assert temporal not in sesion_admin.get(BASE).text

    from fastapi.testclient import TestClient

    otro_cliente = TestClient(client.app)
    entrar(otro_cliente, agente, temporal)
    r = otro_cliente.get("/bandeja", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/mi-cuenta"
    assert otro_cliente.get("/mi-cuenta").status_code == 200


def test_restablecer_desbloquea_el_acceso(db, admin, agente):
    db.execute(
        "UPDATE usuarios SET intentos_fallidos = 3, bloqueado_hasta = '2999-01-01T00:00:00Z'"
    )
    db.commit()
    servicio.restablecer_password(db, agente.id, actor_id=admin.id)
    row = db.execute("SELECT * FROM usuarios WHERE id = ?", (agente.id,)).fetchone()
    assert row["intentos_fallidos"] == 0
    assert row["bloqueado_hasta"] is None


def test_restablecer_genera_contrasenas_distintas(db, admin, agente):
    a = servicio.restablecer_password(db, agente.id, actor_id=admin.id)
    b = servicio.restablecer_password(db, agente.id, actor_id=admin.id)
    assert a != b
    assert len(acciones(db, auditoria.PASSWORD_RESTABLECIDA)) == 2


@pytest.mark.parametrize("accion", ["rol", "desactivar", "reactivar", "restablecer"])
def test_acciones_sobre_usuario_inexistente_devuelven_404(sesion_admin, accion):
    assert post(sesion_admin, f"{BASE}/9999/{accion}", rol="agente").status_code == 404


def test_los_cambios_aparecen_en_la_auditoria(sesion_admin, db, agente):
    post(sesion_admin, f"{BASE}/{agente.id}/desactivar")
    r = sesion_admin.get("/admin/auditoria")
    assert "Usuario desactivado" in r.text
