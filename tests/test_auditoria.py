import json
import sqlite3

import pytest

from app.db import MIGRATIONS, connect, migrate
from app.main import create_app
from app.schemas import TicketCrear
from app.services import auditoria
from app.services import tickets as servicio
from app.services.usuarios import create_user

PASSWORD = "una-clave-segura"
HX = {"HX-Request": "true"}
AHORA = "2026-03-02T09:00:00Z"
TICKET = {
    "asunto": "No puedo acceder a mi factura",
    "texto": "Al pulsar en «Descargar» aparece un error 500.",
    "email_cliente": "cliente@example.com",
    "nombre_cliente": "Laura Gómez",
}


@pytest.fixture
def admin(db):
    return create_user(db, email="admin@example.com", nombre="Root", password=PASSWORD, rol="admin")


@pytest.fixture
def agente(db):
    return create_user(db, email="agente@example.com", nombre="Ana", password=PASSWORD)


def entrar(client, usuario):
    r = client.post(
        "/login", data={"email": usuario.email, "password": PASSWORD}, follow_redirects=False
    )
    assert r.status_code == 303


@pytest.fixture
def sesion(client, agente):
    entrar(client, agente)
    return client


@pytest.fixture
def sesion_admin(client, admin):
    entrar(client, admin)
    return client


def registros(db, accion=None):
    sql = "SELECT * FROM auditoria"
    if accion:
        filas = db.execute(sql + " WHERE accion = ? ORDER BY id", (accion,))
    else:
        filas = db.execute(sql + " ORDER BY id")
    return filas.fetchall()


def crear_ticket(db, reloj):
    return servicio.crear_ticket(db, TicketCrear(**TICKET), reloj)


# --- tickets ---


def test_crear_ticket_registra_usuario_fecha_y_valor_nuevo(sesion, db, agente, reloj):
    r = sesion.post("/api/tickets", json=TICKET)
    assert r.status_code == 201
    (fila,) = registros(db, auditoria.TICKET_CREADO)
    assert fila["usuario_id"] == agente.id
    assert fila["usuario_email"] == agente.email
    assert fila["ticket_id"] == r.json()["id"]
    assert fila["creado_en"] == "2026-03-02T09:00:00Z"
    assert fila["valor_anterior"] is None
    assert fila["valor_nuevo"] == TICKET["asunto"]


def test_la_clasificacion_automatica_del_alta_queda_registrada(sesion, db):
    sesion.post("/api/tickets", json=TICKET)
    (fila,) = registros(db, auditoria.TICKET_CLASIFICADO)
    assert fila["valor_anterior"] == "sin categoría / media"
    assert fila["valor_nuevo"] == "otro / media"


@pytest.mark.parametrize(
    ("cambio", "accion", "anterior", "nuevo"),
    [
        ({"estado": "en_curso"}, auditoria.ESTADO_CAMBIADO, "nuevo", "en_curso"),
        ({"prioridad": "urgente"}, auditoria.PRIORIDAD_CAMBIADA, "media", "urgente"),
        ({"categoria": "tecnico"}, auditoria.CATEGORIA_CAMBIADA, None, "tecnico"),
    ],
)
def test_cambiar_estado_prioridad_o_categoria_registra_anterior_y_nuevo(
    sesion, db, agente, reloj, cambio, accion, anterior, nuevo
):
    ticket = crear_ticket(db, reloj)
    reloj.avanzar(hours=1)
    r = sesion.patch(f"/api/tickets/{ticket.id}", json=cambio)
    assert r.status_code == 200
    (fila,) = registros(db, accion)
    assert fila["usuario_id"] == agente.id
    assert fila["ticket_id"] == ticket.id
    assert fila["creado_en"] == "2026-03-02T10:00:00Z"
    assert (fila["valor_anterior"], fila["valor_nuevo"]) == (anterior, nuevo)


def test_cambiar_la_asignacion_registra_los_emails(sesion, db, agente, reloj):
    otro = create_user(db, email="otro@example.com", nombre="Luis", password=PASSWORD)
    ticket = crear_ticket(db, reloj)
    sesion.patch(f"/api/tickets/{ticket.id}", json={"asignado_a": agente.id})
    sesion.patch(f"/api/tickets/{ticket.id}", json={"asignado_a": otro.id})
    sesion.patch(f"/api/tickets/{ticket.id}", json={"asignado_a": None})
    filas = registros(db, auditoria.ASIGNACION_CAMBIADA)
    assert [(f["valor_anterior"], f["valor_nuevo"]) for f in filas] == [
        (None, "agente@example.com"),
        ("agente@example.com", "otro@example.com"),
        ("otro@example.com", None),
    ]


def test_un_cambio_de_varios_campos_genera_un_registro_por_campo(sesion, db, reloj):
    ticket = crear_ticket(db, reloj)
    sesion.patch(f"/api/tickets/{ticket.id}", json={"estado": "en_curso", "prioridad": "alta"})
    acciones = {f["accion"] for f in registros(db)}
    assert {auditoria.ESTADO_CAMBIADO, auditoria.PRIORIDAD_CAMBIADA} <= acciones


def test_un_cambio_que_no_cambia_nada_no_registra(sesion, db, reloj):
    ticket = crear_ticket(db, reloj)
    antes = len(registros(db))
    sesion.patch(f"/api/tickets/{ticket.id}", json={"prioridad": "media"})
    assert len(registros(db)) == antes


def test_un_cambio_rechazado_no_registra(sesion, db, reloj):
    ticket = crear_ticket(db, reloj)
    sesion.patch(f"/api/tickets/{ticket.id}", json={"estado": "cerrado"})
    antes = len(registros(db))
    assert sesion.patch(f"/api/tickets/{ticket.id}", json={"estado": "nuevo"}).status_code == 409
    assert sesion.patch(f"/api/tickets/{ticket.id}", json={"asignado_a": 999}).status_code == 422
    assert len(registros(db)) == antes


def test_las_acciones_de_la_pantalla_registran_al_usuario(sesion, db, agente, reloj):
    ticket = crear_ticket(db, reloj)
    sesion.post(f"/tickets/{ticket.id}/estado", data={"estado": "en_curso"})
    sesion.post(f"/tickets/{ticket.id}/asignacion", data={"asignado_a": str(agente.id)})
    sesion.post(
        f"/tickets/{ticket.id}/clasificacion", data={"categoria": "envio", "prioridad": "baja"}
    )
    filas = [f for f in registros(db) if f["ticket_id"] == ticket.id][1:]  # sin el alta
    assert [f["accion"] for f in filas] == [
        auditoria.ESTADO_CAMBIADO,
        auditoria.ASIGNACION_CAMBIADA,
        auditoria.PRIORIDAD_CAMBIADA,
        auditoria.CATEGORIA_CAMBIADA,
    ]
    assert {f["usuario_id"] for f in filas} == {agente.id}


def test_reclasificar_registra_anterior_y_nuevo(sesion, db, agente, reloj, llm):
    ticket = crear_ticket(db, reloj)
    llm.contenido = json.dumps(
        {"categoria": "tecnico", "prioridad": "alta", "justificacion": "Error de sistema."}
    )
    assert sesion.post(f"/api/tickets/{ticket.id}/reclasificar").status_code == 200
    (fila,) = registros(db, auditoria.TICKET_RECLASIFICADO)
    assert fila["usuario_id"] == agente.id
    assert fila["ticket_id"] == ticket.id
    assert fila["valor_anterior"] == "sin categoría / media"
    assert fila["valor_nuevo"] == "tecnico / alta"


def test_una_reclasificacion_fallida_no_registra(sesion, db, reloj, llm):
    ticket = crear_ticket(db, reloj)
    llm.contenido = "no es json"
    assert sesion.post(f"/api/tickets/{ticket.id}/reclasificar").status_code == 502
    assert registros(db, auditoria.TICKET_RECLASIFICADO) == []


# --- línea de tiempo ---


def test_los_cambios_aparecen_en_la_linea_de_tiempo(sesion, db, reloj):
    ticket = crear_ticket(db, reloj)
    sesion.patch(f"/api/tickets/{ticket.id}", json={"estado": "en_curso", "prioridad": "urgente"})
    html = sesion.get(f"/tickets/{ticket.id}").text
    assert "Línea de tiempo" in html
    assert "Ticket creado" in html
    assert "Cambio de estado" in html
    assert "Nuevo &rarr; <strong>En curso</strong>" in html
    assert "Media &rarr; <strong>Urgente</strong>" in html
    assert "agente@example.com" in html
    assert "02/03/2026 09:00 UTC" in html


def test_la_linea_de_tiempo_no_mezcla_tickets(sesion, db, reloj):
    uno = crear_ticket(db, reloj)
    otro = crear_ticket(db, reloj)
    sesion.patch(f"/api/tickets/{uno.id}", json={"estado": "cerrado"})
    assert "Cambio de estado" not in sesion.get(f"/tickets/{otro.id}").text


def test_una_accion_htmx_devuelve_la_linea_de_tiempo_actualizada(sesion, db, reloj):
    ticket = crear_ticket(db, reloj)
    r = sesion.post(f"/tickets/{ticket.id}/estado", data={"estado": "resuelto"}, headers=HX)
    assert 'id="historial"' in r.text
    assert 'hx-swap-oob="true"' in r.text.split('id="historial"')[1].split(">")[0]
    assert "Cambio de estado" in r.text


# --- sesión y usuarios ---


def test_login_correcto_registra_usuario_y_fecha(client, db, agente, reloj):
    entrar(client, agente)
    (fila,) = registros(db, auditoria.LOGIN_CORRECTO)
    assert fila["usuario_id"] == agente.id
    assert fila["usuario_email"] == agente.email
    assert fila["creado_en"] == "2026-03-02T09:00:00Z"
    assert fila["ticket_id"] is None


def test_login_fallido_con_contrasena_incorrecta_registra_al_usuario(client, db, agente):
    r = client.post("/login", data={"email": "AGENTE@example.com ", "password": "mala"})
    assert r.status_code == 401
    (fila,) = registros(db, auditoria.LOGIN_FALLIDO)
    assert fila["usuario_id"] == agente.id
    assert fila["usuario_email"] == "agente@example.com"
    assert fila["detalle"] == "Contraseña incorrecta"
    assert registros(db, auditoria.LOGIN_CORRECTO) == []


def test_login_fallido_con_email_desconocido_se_registra_sin_usuario(client, db):
    r = client.post("/login", data={"email": "nadie@example.com", "password": "mala"})
    assert r.status_code == 401
    (fila,) = registros(db, auditoria.LOGIN_FALLIDO)
    assert fila["usuario_id"] is None
    assert fila["usuario_email"] == "nadie@example.com"
    assert fila["detalle"] == "Usuario desconocido"


def test_el_login_fallido_nunca_guarda_la_contrasena(client, db, agente):
    client.post("/login", data={"email": agente.email, "password": "secreto-que-no-debe-guardarse"})
    volcado = json.dumps([dict(f) for f in registros(db)])
    assert "secreto-que-no-debe-guardarse" not in volcado


def test_intentos_con_acceso_bloqueado_se_registran(client, db, agente):
    for _ in range(5):
        client.post("/login", data={"email": agente.email, "password": "mala"})
    client.post("/login", data={"email": agente.email, "password": PASSWORD})
    detalles = [f["detalle"] for f in registros(db, auditoria.LOGIN_FALLIDO)]
    assert detalles == ["Contraseña incorrecta"] * 5 + ["Acceso bloqueado temporalmente"]


def test_crear_usuario_registra_actor_y_valor_nuevo(db, admin, reloj):
    nuevo = create_user(
        db, email="Nuevo@example.com", nombre="N", password=PASSWORD, clock=reloj, actor_id=admin.id
    )
    fila = registros(db, auditoria.USUARIO_CREADO)[-1]
    assert fila["usuario_id"] == admin.id
    assert fila["usuario_email"] == admin.email
    assert fila["valor_anterior"] is None
    assert fila["valor_nuevo"] == f"{nuevo.email} (agente)"
    assert fila["creado_en"] == "2026-03-02T09:00:00Z"


def test_crear_usuario_sin_sesion_se_registra_como_alta_por_linea_de_comandos(db, agente):
    (fila,) = registros(db, auditoria.USUARIO_CREADO)
    assert fila["usuario_id"] is None
    assert "línea de comandos" in fila["detalle"]


def test_un_alta_de_usuario_duplicado_no_registra(db, agente):
    with pytest.raises(Exception):  # noqa: B017
        create_user(db, email=agente.email, nombre="X", password=PASSWORD)
    assert len(registros(db, auditoria.USUARIO_CREADO)) == 1


# --- /admin/auditoria ---


def test_auditoria_exige_sesion_y_rol_admin(client, sesion):
    assert sesion.get("/admin/auditoria").status_code == 403


def test_auditoria_sin_sesion_redirige_al_login(client):
    r = client.get("/admin/auditoria", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, "/login")


def test_el_admin_ve_la_auditoria(sesion_admin, db, agente, reloj):
    crear_ticket(db, reloj)
    html = sesion_admin.get("/admin/auditoria").text
    assert "Auditoría" in html
    assert "Inicio de sesión" in html
    assert "Usuario creado" in html
    assert "Ticket creado" in html
    assert "admin@example.com" in html


def poblar(db, admin, agente):
    auditoria.registrar(
        db,
        auditoria.ESTADO_CAMBIADO,
        ahora="2026-01-10T10:00:00Z",
        usuario_id=agente.id,
        valor_anterior="nuevo",
        valor_nuevo="en_curso",
    )
    auditoria.registrar(
        db,
        auditoria.PRIORIDAD_CAMBIADA,
        ahora="2026-02-10T23:59:59Z",
        usuario_id=admin.id,
        valor_anterior="baja",
        valor_nuevo="alta",
    )
    auditoria.registrar(
        db,
        auditoria.ESTADO_CAMBIADO,
        ahora="2026-02-11T00:00:00Z",
        usuario_id=admin.id,
        valor_anterior="en_curso",
        valor_nuevo="cerrado",
    )
    db.commit()


def ids(db, **filtros):
    return [r.valor_nuevo for r in auditoria.listar(db, **filtros).items]


def test_filtro_por_usuario(db, admin, agente):
    poblar(db, admin, agente)
    assert ids(db, usuario=str(agente.id), accion=auditoria.ESTADO_CAMBIADO) == ["en_curso"]
    assert ids(db, usuario=admin.email, accion=auditoria.ESTADO_CAMBIADO) == ["cerrado"]


def test_filtro_por_accion(db, admin, agente):
    poblar(db, admin, agente)
    assert ids(db, accion=auditoria.PRIORIDAD_CAMBIADA) == ["alta"]
    assert ids(db, accion=auditoria.ESTADO_CAMBIADO) == ["cerrado", "en_curso"]


def test_filtro_por_rango_de_fechas_incluye_ambos_extremos(db, admin, agente):
    poblar(db, admin, agente)
    assert ids(db, accion=auditoria.ESTADO_CAMBIADO, desde="2026-01-10", hasta="2026-01-10") == [
        "en_curso"
    ]
    assert ids(db, accion=auditoria.PRIORIDAD_CAMBIADA, desde="2026-02-10", hasta="2026-02-10") == [
        "alta"
    ]
    assert ids(db, accion=auditoria.ESTADO_CAMBIADO, desde="2026-02-11") == ["cerrado"]
    assert ids(db, accion=auditoria.ESTADO_CAMBIADO, hasta="2026-02-10") == ["en_curso"]


def test_filtros_combinados_desde_la_pagina(sesion_admin, db, admin, agente):
    poblar(db, admin, agente)
    r = sesion_admin.get(
        "/admin/auditoria",
        params={"usuario": admin.id, "accion": "estado_cambiado", "desde": "2026-02-01"},
    )
    assert r.status_code == 200
    assert "Cerrado" in r.text
    assert "En curso" in r.text  # valor anterior del único registro que coincide
    assert "Alta" not in r.text.split("<tbody>")[1]


def test_una_fecha_invalida_da_422_con_mensaje(sesion_admin):
    r = sesion_admin.get("/admin/auditoria", params={"desde": "ayer"})
    assert r.status_code == 422
    assert "La fecha «desde» no es válida." in r.text


@pytest.mark.parametrize("usuario", ["99999999999999999999", str(2**63)])
def test_un_usuario_numerico_fuera_de_rango_da_422_y_no_500(sesion_admin, usuario):
    r = sesion_admin.get("/admin/auditoria", params={"usuario": usuario})
    assert r.status_code == 422
    assert "El usuario indicado no es válido." in r.text


def test_el_id_de_usuario_maximo_de_sqlite_es_valido(sesion_admin):
    r = sesion_admin.get("/admin/auditoria", params={"usuario": str(2**63 - 1)})
    assert r.status_code == 200


def test_un_rango_invertido_da_422(sesion_admin):
    r = sesion_admin.get("/admin/auditoria", params={"desde": "2026-03-02", "hasta": "2026-03-01"})
    assert r.status_code == 422


def test_sin_resultados_muestra_un_mensaje(sesion_admin):
    r = sesion_admin.get("/admin/auditoria", params={"accion": "no_existe"})
    assert r.status_code == 200
    assert "No hay registros de auditoría" in r.text


def test_la_auditoria_se_pagina_conservando_los_filtros(sesion_admin, db, admin):
    for _ in range(auditoria.TAMANO_PAGINA + 1):
        auditoria.registrar(db, auditoria.ESTADO_CAMBIADO, ahora=AHORA, usuario_id=admin.id)
    db.commit()
    r = sesion_admin.get("/admin/auditoria", params={"accion": "estado_cambiado"})
    assert "Página 1 de 2" in r.text
    assert "accion=estado_cambiado&amp;page=2" in r.text
    assert (
        "Página 2 de 2"
        in sesion_admin.get(
            "/admin/auditoria", params={"accion": "estado_cambiado", "page": 2}
        ).text
    )


def test_el_texto_de_la_auditoria_se_escapa(sesion_admin, db):
    auditoria.registrar(
        db, auditoria.LOGIN_FALLIDO, ahora=AHORA, usuario_email="<script>x</script>"
    )
    db.commit()
    html = sesion_admin.get("/admin/auditoria").text
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


# --- inmutabilidad ---


def test_no_existe_ninguna_ruta_que_modifique_la_auditoria(settings):
    rutas = {
        ruta: metodos
        for ruta, metodos in create_app(settings).openapi()["paths"].items()
        if "auditoria" in ruta
    }
    assert rutas
    for ruta, metodos in rutas.items():
        assert set(metodos) == {"get"}, ruta


@pytest.mark.parametrize("metodo", ["post", "put", "patch", "delete"])
def test_modificar_o_borrar_por_http_no_esta_permitido(sesion_admin, metodo):
    for ruta in ("/admin/auditoria", "/admin/auditoria/1", "/api/auditoria", "/api/auditoria/1"):
        r = getattr(sesion_admin, metodo)(ruta)
        assert r.status_code in (404, 405)


def test_la_base_de_datos_rechaza_borrar_registros(db, agente):
    with pytest.raises(sqlite3.IntegrityError, match="no se pueden borrar"):
        db.execute("DELETE FROM auditoria")


@pytest.mark.parametrize(
    "asignacion",
    [
        "accion = 'otra'",
        "valor_nuevo = 'manipulado'",
        "valor_anterior = 'manipulado'",
        "creado_en = '2000-01-01T00:00:00Z'",
        "usuario_email = 'falso@example.com'",
        "usuario_id = NULL",
        "detalle = 'x'",
    ],
)
def test_la_base_de_datos_rechaza_modificar_registros(db, agente, asignacion):
    auditoria.registrar(db, auditoria.LOGIN_CORRECTO, ahora=AHORA, usuario_id=agente.id)
    db.commit()
    with pytest.raises(sqlite3.IntegrityError, match="no se pueden modificar"):
        db.execute(f"UPDATE auditoria SET {asignacion}")


def test_no_se_puede_desvincular_un_registro_de_un_ticket_existente(db, reloj):
    ticket = crear_ticket(db, reloj)
    with pytest.raises(sqlite3.IntegrityError, match="no se pueden modificar"):
        db.execute("UPDATE auditoria SET ticket_id = NULL WHERE ticket_id = ?", (ticket.id,))


def test_borrar_un_ticket_conserva_el_registro_de_auditoria(db, agente, reloj):
    ticket = crear_ticket(db, reloj)
    db.execute("DELETE FROM tickets WHERE id = ?", (ticket.id,))
    (fila,) = registros(db, auditoria.TICKET_CREADO)
    assert fila["ticket_id"] is None
    assert fila["valor_nuevo"] == TICKET["asunto"]


def test_la_migracion_conserva_los_registros_anteriores(settings):
    conn = connect(settings.database_path)
    migrate(conn, MIGRATIONS[:3])
    conn.execute(
        "INSERT INTO auditoria (accion, detalle, creado_en) VALUES ('antigua', 'd', ?)", (AHORA,)
    )
    conn.commit()
    assert migrate(conn, MIGRATIONS[:4]) == [4]
    fila = conn.execute("SELECT * FROM auditoria").fetchone()
    assert (fila["accion"], fila["detalle"], fila["valor_nuevo"]) == ("antigua", "d", None)
    conn.close()
