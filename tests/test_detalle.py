import pytest

from app.db import MIGRATIONS, connect, migrate
from app.schemas import TRANSICIONES
from app.services import tickets as servicio
from app.services.usuarios import create_user

PASSWORD = "una-clave-segura"
HX = {"HX-Request": "true"}

TRANSICIONES_VALIDAS = [
    ("nuevo", "en_curso"),
    ("nuevo", "esperando_cliente"),
    ("nuevo", "resuelto"),
    ("nuevo", "cerrado"),
    ("en_curso", "esperando_cliente"),
    ("en_curso", "resuelto"),
    ("en_curso", "cerrado"),
    ("esperando_cliente", "en_curso"),
    ("esperando_cliente", "resuelto"),
    ("esperando_cliente", "cerrado"),
    ("resuelto", "en_curso"),
    ("resuelto", "cerrado"),
    ("cerrado", "en_curso"),
]
TRANSICIONES_INVALIDAS = [
    ("en_curso", "nuevo"),
    ("esperando_cliente", "nuevo"),
    ("resuelto", "nuevo"),
    ("cerrado", "nuevo"),
    ("resuelto", "esperando_cliente"),
    ("cerrado", "esperando_cliente"),
    ("cerrado", "resuelto"),
]


@pytest.fixture
def agente(db):
    return create_user(db, email="agente@example.com", nombre="Ana", password=PASSWORD)


@pytest.fixture
def otro(db):
    return create_user(db, email="otro@example.com", nombre="Luis", password=PASSWORD)


@pytest.fixture
def sesion(client, agente):
    r = client.post(
        "/login", data={"email": agente.email, "password": PASSWORD}, follow_redirects=False
    )
    assert r.status_code == 303
    return client


@pytest.fixture
def crear(db):
    def _crear(
        *,
        estado="nuevo",
        prioridad="media",
        categoria="otro",
        asignado_a=None,
        resumen_ia="Consulta general sin urgencia.",
    ):
        cursor = db.execute(
            "INSERT INTO tickets (asunto, descripcion, solicitante_nombre, solicitante_email, "
            "estado, prioridad, categoria, resumen_ia, asignado_a, creado_en, actualizado_en) "
            "VALUES ('No puedo entrar', 'Línea 1\nLínea <b>2</b>', 'Marta Pérez', "
            "'marta@example.com', ?, ?, ?, ?, ?, '2026-03-02T06:30:00Z', '2026-03-02T06:30:00Z')",
            (estado, prioridad, categoria, resumen_ia, asignado_a),
        )
        db.commit()
        return cursor.lastrowid

    return _crear


def fila(db, ticket_id):
    return dict(db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone())


# --- pantalla de detalle ---


def test_el_detalle_muestra_los_datos_del_ticket(sesion, crear, agente):
    ticket_id = crear(categoria="cuenta", prioridad="alta", asignado_a=agente.id)
    r = sesion.get(f"/tickets/{ticket_id}")
    assert r.status_code == 200
    assert "No puedo entrar" in r.text
    assert "Línea 1\nLínea &lt;b&gt;2&lt;/b&gt;" in r.text
    assert "Marta Pérez" in r.text
    assert "marta@example.com" in r.text
    assert "02/03/2026 06:30 UTC" in r.text
    assert "Cuenta" in r.text
    assert "Alta" in r.text
    assert "Consulta general sin urgencia." in r.text
    assert 'id="panel-asignacion"' in r.text
    assert "<p>Ana</p>" in r.text
    assert "Sin plazo definido" in r.text


def test_el_detalle_de_un_ticket_sin_asignar_ni_justificacion(sesion, crear):
    ticket_id = crear(resumen_ia=None)
    texto = sesion.get(f"/tickets/{ticket_id}").text
    assert "Sin asignar" in texto
    assert "Sin justificación de la IA." in texto


def test_ticket_inexistente_da_404_html(sesion):
    r = sesion.get("/tickets/999")
    assert r.status_code == 404
    assert "Ticket no encontrado" in r.text
    assert "<html" in r.text


def test_sin_sesion_redirige_al_login(client, crear):
    ticket_id = crear()
    r = client.get(f"/tickets/{ticket_id}", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, "/login")
    r = client.post(
        f"/tickets/{ticket_id}/estado", data={"estado": "en_curso"}, follow_redirects=False
    )
    assert (r.status_code, r.headers["location"]) == (303, "/login")


def test_las_acciones_usan_htmx_y_apuntan_a_su_panel(sesion, crear):
    texto = sesion.get(f"/tickets/{crear()}").text
    assert 'src="https://unpkg.com/htmx.org@2.0.4"' in texto
    for panel, ruta in (
        ("panel-estado", "estado"),
        ("panel-asignacion", "asignacion"),
        ("panel-clasificacion", "clasificacion"),
    ):
        assert f'hx-target="#{panel}"' in texto
        assert f'hx-post="/tickets/1/{ruta}"' in texto


# --- tabla de transiciones ---


def test_la_tabla_de_transiciones_es_la_esperada():
    definidas = {(o, d) for o, destinos in TRANSICIONES.items() for d in destinos}
    assert definidas == set(TRANSICIONES_VALIDAS)
    assert set(TRANSICIONES) == {"nuevo", "en_curso", "esperando_cliente", "resuelto", "cerrado"}


@pytest.mark.parametrize(("origen", "destino"), TRANSICIONES_VALIDAS)
def test_transicion_valida_en_el_servicio(db, crear, origen, destino):
    ticket_id = crear(estado=origen)
    assert servicio.actualizar_ticket(db, ticket_id, {"estado": destino}).estado == destino
    assert fila(db, ticket_id)["estado"] == destino


@pytest.mark.parametrize(("origen", "destino"), TRANSICIONES_VALIDAS)
def test_transicion_valida_desde_la_pantalla(sesion, db, crear, origen, destino):
    ticket_id = crear(estado=origen)
    r = sesion.post(f"/tickets/{ticket_id}/estado", data={"estado": destino}, headers=HX)
    assert r.status_code == 200
    assert f"etiqueta-estado-{destino}" in r.text
    assert fila(db, ticket_id)["estado"] == destino


@pytest.mark.parametrize(("origen", "destino"), TRANSICIONES_INVALIDAS)
def test_transicion_invalida_da_error_y_no_cambia_nada(sesion, db, crear, origen, destino):
    ticket_id = crear(estado=origen)
    antes = fila(db, ticket_id)
    r = sesion.post(f"/tickets/{ticket_id}/estado", data={"estado": destino}, headers=HX)
    assert r.status_code == 409
    assert 'role="alert"' in r.text
    assert f"etiqueta-estado-{origen}" in r.text
    assert fila(db, ticket_id) == antes


@pytest.mark.parametrize(("origen", "destino"), TRANSICIONES_INVALIDAS)
def test_transicion_invalida_en_el_servicio_y_en_la_api(sesion, db, crear, origen, destino):
    ticket_id = crear(estado=origen)
    antes = fila(db, ticket_id)
    with pytest.raises(servicio.TransicionNoPermitidaError):
        servicio.actualizar_ticket(db, ticket_id, {"estado": destino, "prioridad": "alta"})
    r = sesion.patch(f"/api/tickets/{ticket_id}", json={"estado": destino, "prioridad": "alta"})
    assert r.status_code == 409
    assert fila(db, ticket_id) == antes


def test_estado_desconocido_da_422_y_no_cambia_nada(sesion, db, crear):
    ticket_id = crear()
    antes = fila(db, ticket_id)
    for valor in ("inventado", ""):
        r = sesion.post(f"/tickets/{ticket_id}/estado", data={"estado": valor}, headers=HX)
        assert r.status_code == 422
    assert fila(db, ticket_id) == antes


def test_el_selector_solo_ofrece_transiciones_permitidas(sesion, crear):
    texto = sesion.get(f"/tickets/{crear(estado='resuelto')}").text
    assert '<option value="en_curso">' in texto
    assert '<option value="cerrado">' in texto
    assert '<option value="nuevo">' not in texto
    assert '<option value="esperando_cliente">' not in texto


def test_resolver_fija_resuelto_en_con_el_reloj_y_reabrir_lo_limpia(sesion, db, crear, reloj):
    ticket_id = crear(estado="en_curso")
    reloj.avanzar(hours=3)
    sesion.post(f"/tickets/{ticket_id}/estado", data={"estado": "resuelto"}, headers=HX)
    assert fila(db, ticket_id)["resuelto_en"] == "2026-03-02T12:00:00Z"
    sesion.post(f"/tickets/{ticket_id}/estado", data={"estado": "en_curso"}, headers=HX)
    assert fila(db, ticket_id)["resuelto_en"] is None


# --- respuestas parciales HTMX ---


def test_htmx_devuelve_solo_el_panel_y_las_fechas_fuera_de_banda(sesion, crear, reloj):
    ticket_id = crear()
    reloj.avanzar(hours=1)
    r = sesion.post(f"/tickets/{ticket_id}/estado", data={"estado": "en_curso"}, headers=HX)
    assert "<html" not in r.text
    assert r.text.lstrip().startswith('<section id="panel-estado"')
    assert 'id="fechas"' in r.text and 'hx-swap-oob="true"' in r.text
    assert "02/03/2026 10:00 UTC" in r.text
    assert 'id="panel-asignacion"' not in r.text
    assert 'id="panel-clasificacion"' not in r.text


def test_sin_htmx_las_acciones_redirigen_al_detalle(sesion, db, crear):
    ticket_id = crear()
    r = sesion.post(
        f"/tickets/{ticket_id}/estado", data={"estado": "en_curso"}, follow_redirects=False
    )
    assert (r.status_code, r.headers["location"]) == (303, f"/tickets/{ticket_id}")
    assert fila(db, ticket_id)["estado"] == "en_curso"


def test_sin_htmx_un_error_repinta_la_pagina_entera(sesion, db, crear):
    ticket_id = crear(estado="cerrado")
    r = sesion.post(f"/tickets/{ticket_id}/estado", data={"estado": "nuevo"})
    assert r.status_code == 409
    assert "<html" in r.text
    assert 'role="alert"' in r.text
    assert fila(db, ticket_id)["estado"] == "cerrado"


def test_accion_sobre_ticket_inexistente_da_404(sesion):
    r = sesion.post("/tickets/999/estado", data={"estado": "en_curso"}, headers=HX)
    assert r.status_code == 404


# --- asignación ---


def test_asignar_a_un_agente_activo(sesion, db, crear, otro):
    ticket_id = crear()
    r = sesion.post(f"/tickets/{ticket_id}/asignacion", data={"asignado_a": otro.id}, headers=HX)
    assert r.status_code == 200
    assert "<p>Luis</p>" in r.text
    assert fila(db, ticket_id)["asignado_a"] == otro.id


def test_boton_asignarme(sesion, db, crear, agente):
    ticket_id = crear()
    pagina = sesion.get(f"/tickets/{ticket_id}").text
    assert "Asignarme" in pagina
    assert f'<input type="hidden" name="asignado_a" value="{agente.id}">' in pagina
    r = sesion.post(f"/tickets/{ticket_id}/asignacion", data={"asignado_a": agente.id}, headers=HX)
    assert "<p>Ana</p>" in r.text
    assert "Asignarme" not in r.text
    assert fila(db, ticket_id)["asignado_a"] == agente.id


def test_desasignar(sesion, db, crear, otro):
    ticket_id = crear(asignado_a=otro.id)
    r = sesion.post(f"/tickets/{ticket_id}/asignacion", data={"asignado_a": ""}, headers=HX)
    assert r.status_code == 200
    assert fila(db, ticket_id)["asignado_a"] is None


def test_no_se_asigna_a_un_usuario_desactivado(sesion, db, crear, otro):
    ticket_id = crear()
    db.execute("UPDATE usuarios SET activo = 0 WHERE id = ?", (otro.id,))
    db.commit()
    texto = sesion.get(f"/tickets/{ticket_id}").text
    assert f'<option value="{otro.id}"' not in texto
    r = sesion.post(f"/tickets/{ticket_id}/asignacion", data={"asignado_a": otro.id}, headers=HX)
    assert r.status_code == 422
    assert fila(db, ticket_id)["asignado_a"] is None


@pytest.mark.parametrize("valor", ["999", "abc", "0", "-3", "99999999999999999999"])
def test_asignacion_invalida_da_422_y_no_cambia_nada(sesion, db, crear, otro, valor):
    ticket_id = crear(asignado_a=otro.id)
    r = sesion.post(f"/tickets/{ticket_id}/asignacion", data={"asignado_a": valor}, headers=HX)
    assert r.status_code == 422
    assert fila(db, ticket_id)["asignado_a"] == otro.id


def test_si_el_asignado_se_desactiva_el_detalle_sigue_funcionando(sesion, db, crear, otro):
    ticket_id = crear(asignado_a=otro.id)
    db.execute("UPDATE usuarios SET activo = 0 WHERE id = ?", (otro.id,))
    db.commit()
    r = sesion.get(f"/tickets/{ticket_id}")
    assert r.status_code == 200
    assert "Luis" in r.text and "desactivado" in r.text


# --- corrección de la clasificación ---


def test_un_ticket_clasificado_por_la_ia_no_figura_como_corregido(sesion, crear):
    assert "Corregido por una persona" not in sesion.get(f"/tickets/{crear()}").text


def test_cambiar_categoria_marca_el_ticket_como_corregido(sesion, db, crear):
    ticket_id = crear(categoria="otro", prioridad="media")
    r = sesion.post(
        f"/tickets/{ticket_id}/clasificacion",
        data={"categoria": "facturacion", "prioridad": "media"},
        headers=HX,
    )
    assert r.status_code == 200
    assert "Corregido por una persona" in r.text
    datos = fila(db, ticket_id)
    assert (datos["categoria"], datos["prioridad"], datos["corregido_por_persona"]) == (
        "facturacion",
        "media",
        1,
    )
    assert "Corregido por una persona" in sesion.get(f"/tickets/{ticket_id}").text


def test_cambiar_prioridad_marca_el_ticket_como_corregido(sesion, db, crear):
    ticket_id = crear(categoria="otro", prioridad="media")
    sesion.post(
        f"/tickets/{ticket_id}/clasificacion",
        data={"categoria": "otro", "prioridad": "urgente"},
        headers=HX,
    )
    datos = fila(db, ticket_id)
    assert (datos["prioridad"], datos["corregido_por_persona"]) == ("urgente", 1)


def test_guardar_los_mismos_valores_no_marca_el_ticket(sesion, db, crear):
    ticket_id = crear(categoria="otro", prioridad="media")
    sesion.post(
        f"/tickets/{ticket_id}/clasificacion",
        data={"categoria": "otro", "prioridad": "media"},
        headers=HX,
    )
    assert fila(db, ticket_id)["corregido_por_persona"] == 0


def test_cambiar_estado_o_asignacion_no_marca_el_ticket(sesion, db, crear, agente):
    ticket_id = crear()
    sesion.post(f"/tickets/{ticket_id}/estado", data={"estado": "en_curso"}, headers=HX)
    sesion.post(f"/tickets/{ticket_id}/asignacion", data={"asignado_a": agente.id}, headers=HX)
    assert fila(db, ticket_id)["corregido_por_persona"] == 0


def test_la_correccion_por_la_api_tambien_marca_el_ticket(sesion, db, crear):
    ticket_id = crear(categoria="otro")
    assert sesion.patch(f"/api/tickets/{ticket_id}", json={"categoria": "tecnico"}).json()[
        "corregido_por_persona"
    ]


def test_reclasificar_con_ia_quita_la_marca(sesion, db, crear):
    ticket_id = crear()
    sesion.post(f"/tickets/{ticket_id}/clasificacion", data={"prioridad": "alta"}, headers=HX)
    assert fila(db, ticket_id)["corregido_por_persona"] == 1
    assert sesion.post(f"/api/tickets/{ticket_id}/reclasificar").status_code == 200
    assert fila(db, ticket_id)["corregido_por_persona"] == 0


def test_se_puede_corregir_solo_una_de_las_dos(sesion, db, crear):
    ticket_id = crear(categoria="otro", prioridad="media")
    sesion.post(f"/tickets/{ticket_id}/clasificacion", data={"prioridad": "baja"}, headers=HX)
    datos = fila(db, ticket_id)
    assert (datos["categoria"], datos["prioridad"]) == ("otro", "baja")


@pytest.mark.parametrize(
    "datos",
    [
        {},
        {"categoria": "inventada"},
        {"prioridad": "máxima"},
        {"categoria": "otro", "prioridad": "x"},
    ],
)
def test_correccion_invalida_da_422_y_no_cambia_nada(sesion, db, crear, datos):
    ticket_id = crear(categoria="tecnico", prioridad="baja")
    antes = fila(db, ticket_id)
    r = sesion.post(f"/tickets/{ticket_id}/clasificacion", data=datos, headers=HX)
    assert r.status_code == 422
    assert 'role="alert"' in r.text
    assert fila(db, ticket_id) == antes


# --- migración ---


def test_la_migracion_renombra_los_estados_antiguos(settings):
    conn = connect(settings.database_path)
    migrate(conn, MIGRATIONS[:2])
    for estado in ("en_progreso", "pendiente", "nuevo"):
        conn.execute(
            "INSERT INTO tickets (asunto, descripcion, solicitante_nombre, solicitante_email, "
            "estado, creado_en, actualizado_en) VALUES ('a', 'b', 'c', 'd@e.es', ?, 't', 't')",
            (estado,),
        )
    conn.commit()
    assert migrate(conn, MIGRATIONS[:3]) == [3]
    filas = conn.execute("SELECT estado, corregido_por_persona FROM tickets ORDER BY id")
    assert [tuple(f) for f in filas] == [
        ("en_curso", 0),
        ("esperando_cliente", 0),
        ("nuevo", 0),
    ]
    conn.close()
