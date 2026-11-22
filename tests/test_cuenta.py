import pytest

from app.auth import verify_password
from app.services import auditoria
from app.services.usuarios import create_user

PASSWORD = "una-clave-segura"
NUEVA = "otra-clave-distinta"


@pytest.fixture
def agente(db):
    return create_user(db, email="agente@example.com", nombre="Ana", password=PASSWORD)


@pytest.fixture
def sesion(client, agente):
    r = client.post(
        "/login", data={"email": agente.email, "password": PASSWORD}, follow_redirects=False
    )
    assert r.status_code == 303
    return client


def cambiar(client, actual=PASSWORD, nueva=NUEVA, confirmacion=None):
    return client.post(
        "/mi-cuenta/password",
        data={
            "actual": actual,
            "nueva": nueva,
            "confirmacion": nueva if confirmacion is None else confirmacion,
        },
        follow_redirects=False,
    )


def hash_actual(db, user_id):
    return db.execute("SELECT password_hash FROM usuarios WHERE id = ?", (user_id,)).fetchone()[0]


def test_mi_cuenta_requiere_sesion(client):
    r = client.get("/mi-cuenta", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
    assert client.post("/mi-cuenta/password", data={}, follow_redirects=False).status_code == 303


def test_mi_cuenta_muestra_los_datos_del_usuario(sesion):
    r = sesion.get("/mi-cuenta")
    assert r.status_code == 200
    assert "agente@example.com" in r.text
    assert "Cambiar contraseña" in r.text


def test_cualquier_rol_puede_cambiar_su_contrasena(client, db):
    admin = create_user(
        db, email="admin@example.com", nombre="Root", password=PASSWORD, rol="admin"
    )
    client.post("/login", data={"email": admin.email, "password": PASSWORD})
    r = cambiar(client)
    assert r.status_code == 303
    assert verify_password(NUEVA, hash_actual(db, admin.id))


def test_cambiar_contrasena_con_la_actual_correcta(sesion, db, agente):
    r = cambiar(sesion)
    assert r.status_code == 303
    assert r.headers["location"] == "/mi-cuenta"
    assert verify_password(NUEVA, hash_actual(db, agente.id))
    assert "Contraseña actualizada" in sesion.get("/mi-cuenta").text
    fila = db.execute(
        "SELECT * FROM auditoria WHERE accion = ?", (auditoria.PASSWORD_CAMBIADA,)
    ).fetchone()
    assert fila["usuario_id"] == agente.id
    assert NUEVA not in str(dict(fila))


def test_la_nueva_contrasena_sirve_para_iniciar_sesion(sesion, client, agente):
    cambiar(sesion)
    from fastapi.testclient import TestClient

    nuevo = TestClient(client.app)
    ok = nuevo.post("/login", data={"email": agente.email, "password": NUEVA})
    assert ok.status_code == 200 or ok.history  # redirige a la bandeja
    viejo = TestClient(client.app).post(
        "/login", data={"email": agente.email, "password": PASSWORD}, follow_redirects=False
    )
    assert viejo.status_code == 401


def test_contrasena_actual_incorrecta(sesion, db, agente):
    antes = hash_actual(db, agente.id)
    r = cambiar(sesion, actual="no-es-esta-clave")
    assert r.status_code == 422
    assert "contraseña actual no es correcta" in r.text
    assert hash_actual(db, agente.id) == antes


@pytest.mark.parametrize(
    ("nueva", "confirmacion", "texto"),
    [
        ("corta", None, "al menos"),
        (NUEVA, "otra-cosa-distinta", "confirmación no coincide"),
        (PASSWORD, None, "distinta de la actual"),
    ],
)
def test_nueva_contrasena_invalida(sesion, db, agente, nueva, confirmacion, texto):
    antes = hash_actual(db, agente.id)
    r = cambiar(sesion, nueva=nueva, confirmacion=confirmacion)
    assert r.status_code == 422
    assert texto in r.text
    assert hash_actual(db, agente.id) == antes


def test_con_contrasena_temporal_solo_se_puede_cambiarla(sesion, db, agente):
    db.execute("UPDATE usuarios SET debe_cambiar_password = 1")
    db.commit()
    for ruta in ("/bandeja", "/panel", "/tickets/1", "/admin"):
        r = sesion.get(ruta, follow_redirects=False)
        assert r.status_code == 303, ruta
        assert r.headers["location"] == "/mi-cuenta"
    assert sesion.get("/api/tickets").status_code == 403
    page = sesion.get("/mi-cuenta")
    assert page.status_code == 200
    assert "contraseña temporal" in page.text

    assert cambiar(sesion).status_code == 303
    assert sesion.get("/bandeja").status_code == 200


def test_con_contrasena_temporal_se_puede_cerrar_sesion(sesion, db):
    db.execute("UPDATE usuarios SET debe_cambiar_password = 1")
    db.commit()
    r = sesion.post("/logout", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
