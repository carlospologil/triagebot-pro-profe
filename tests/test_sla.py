import re
from datetime import UTC, datetime

import pytest

from app.schemas import TicketCrear
from app.services import sla
from app.services import tickets as servicio
from app.services.usuarios import create_user

PASSWORD = "una-clave-segura"
HX = {"HX-Request": "true"}
AHORA = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
CREADO = "2026-03-02T09:00:00Z"


@pytest.fixture
def sesion(client, db):
    usuario = create_user(db, email="agente@example.com", nombre="Ana", password=PASSWORD)
    r = client.post(
        "/login", data={"email": usuario.email, "password": PASSWORD}, follow_redirects=False
    )
    assert r.status_code == 303
    return client


@pytest.fixture
def crear(db):
    def _crear(
        asunto="Ticket",
        *,
        estado="nuevo",
        prioridad="media",
        creado=CREADO,
        fecha_limite="auto",
    ):
        if fecha_limite == "auto":
            fecha_limite = sla.calcular_fecha_limite(creado, prioridad)
        cursor = db.execute(
            "INSERT INTO tickets (asunto, descripcion, solicitante_nombre, solicitante_email, "
            "estado, prioridad, categoria, fecha_limite, creado_en, actualizado_en) "
            "VALUES (?, 'Texto', 'Laura', 'laura@example.com', ?, ?, 'otro', ?, ?, ?)",
            (asunto, estado, prioridad, fecha_limite, creado, creado),
        )
        db.commit()
        return cursor.lastrowid

    return _crear


def asuntos(respuesta) -> list[str]:
    return re.findall(r'<td class="col-asunto"><a href="/tickets/\d+">([^<]*)</a>', respuesta.text)


def fila(db, ticket_id):
    return dict(db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone())


def nuevo_por_api(cliente):
    r = cliente.post("/api/tickets", json={"asunto": "A", "texto": "B", "email_cliente": "a@b.es"})
    assert r.status_code == 201
    return r.json()


# --- cálculo del plazo ---


@pytest.mark.parametrize(
    ("prioridad", "esperada"),
    [
        ("alta", "2026-03-02T13:00:00Z"),
        ("media", "2026-03-03T09:00:00Z"),
        ("baja", "2026-03-05T09:00:00Z"),
        ("urgente", "2026-03-02T13:00:00Z"),
    ],
)
def test_el_plazo_depende_de_la_prioridad(prioridad, esperada):
    assert sla.calcular_fecha_limite(CREADO, prioridad) == esperada


def test_el_plazo_cruza_fin_de_anio():
    assert sla.calcular_fecha_limite("2026-12-31T23:00:00Z", "media") == "2027-01-01T23:00:00Z"


# --- vencimiento ---


def test_un_ticket_abierto_vence_solo_despues_de_la_fecha_limite(reloj):
    limite = "2026-03-02T13:00:00Z"
    reloj.ahora = datetime(2026, 3, 2, 12, 59, 59, tzinfo=UTC)
    assert not sla.esta_vencido(limite, "nuevo", reloj())
    reloj.ahora = datetime(2026, 3, 2, 13, 0, 0, tzinfo=UTC)
    assert not sla.esta_vencido(limite, "nuevo", reloj())
    reloj.avanzar(seconds=1)
    assert sla.esta_vencido(limite, "nuevo", reloj())


@pytest.mark.parametrize("estado", ["nuevo", "en_curso", "esperando_cliente"])
def test_los_estados_abiertos_pueden_vencer(estado):
    assert sla.esta_vencido("2026-03-01T00:00:00Z", estado, AHORA)


@pytest.mark.parametrize("estado", ["resuelto", "cerrado"])
def test_un_ticket_resuelto_o_cerrado_nunca_esta_vencido(estado):
    assert not sla.esta_vencido("2026-03-01T00:00:00Z", estado, AHORA)


def test_sin_fecha_limite_no_hay_vencimiento_ni_plazo():
    assert not sla.esta_vencido(None, "nuevo", AHORA)
    assert sla.calcular_plazo(None, "nuevo", AHORA) is None


def test_el_plazo_de_un_ticket_terminado_no_se_muestra():
    assert sla.calcular_plazo("2026-03-01T00:00:00Z", "resuelto", AHORA) is None


@pytest.mark.parametrize(
    ("limite", "vencido", "texto"),
    [
        ("2026-03-02T09:00:30Z", False, "Quedan menos de 1 min"),
        ("2026-03-02T09:45:00Z", False, "Quedan 45 min"),
        ("2026-03-02T12:00:00Z", False, "Quedan 3 h"),
        ("2026-03-02T12:20:00Z", False, "Quedan 3 h 20 min"),
        ("2026-03-04T15:00:00Z", False, "Quedan 2 d 6 h"),
        ("2026-03-02T08:30:00Z", True, "Excedido por 30 min"),
        ("2026-03-02T06:00:00Z", True, "Excedido por 3 h"),
        ("2026-02-28T09:00:00Z", True, "Excedido por 2 d"),
    ],
)
def test_texto_del_tiempo_restante_o_excedido(limite, vencido, texto):
    assert sla.calcular_plazo(limite, "en_curso", AHORA) == sla.Plazo(vencido, texto)


# --- fecha límite al crear y recalcular ---


def test_al_crear_se_calcula_la_fecha_limite_con_el_reloj(db, reloj):
    reloj.avanzar(hours=5, minutes=7)
    ticket = servicio.crear_ticket(
        db, TicketCrear(asunto="Hola", texto="Texto", email_cliente="a@b.es"), reloj
    )
    assert ticket.creado_en == "2026-03-02T14:07:00Z"
    assert ticket.fecha_limite == "2026-03-03T14:07:00Z"


def test_la_api_devuelve_la_fecha_limite_de_la_prioridad_clasificada(sesion, llm):
    llm.contenido = '{"categoria": "tecnico", "prioridad": "alta", "justificacion": "Caída."}'
    ticket = nuevo_por_api(sesion)
    assert ticket["prioridad"] == "alta"
    assert ticket["fecha_limite"] == "2026-03-02T13:00:00Z"


def test_si_la_ia_falla_el_ticket_conserva_el_plazo_de_prioridad_media(sesion, llm):
    llm.contenido = "esto no es json"
    ticket = nuevo_por_api(sesion)
    assert ticket["categoria"] == "sin_clasificar"
    assert ticket["fecha_limite"] == "2026-03-03T09:00:00Z"


@pytest.mark.parametrize(
    ("prioridad", "esperada"),
    [
        ("alta", "2026-03-02T13:00:00Z"),
        ("baja", "2026-03-05T09:00:00Z"),
        ("media", "2026-03-03T09:00:00Z"),
    ],
)
def test_cambiar_la_prioridad_recalcula_el_plazo_desde_la_creacion(
    db, reloj, crear, prioridad, esperada
):
    ticket_id = crear(prioridad="media")
    reloj.avanzar(hours=2)
    servicio.actualizar_ticket(db, ticket_id, {"prioridad": prioridad}, reloj)
    assert fila(db, ticket_id)["fecha_limite"] == esperada


def test_otros_cambios_no_tocan_la_fecha_limite(db, reloj, crear):
    ticket_id = crear(prioridad="alta")
    antes = fila(db, ticket_id)["fecha_limite"]
    servicio.actualizar_ticket(db, ticket_id, {"estado": "en_curso", "categoria": "tecnico"}, reloj)
    assert fila(db, ticket_id)["fecha_limite"] == antes


def test_la_api_recalcula_el_plazo_al_cambiar_la_prioridad(sesion, reloj):
    ticket = nuevo_por_api(sesion)
    assert ticket["fecha_limite"] == "2026-03-03T09:00:00Z"
    reloj.avanzar(hours=1)
    r = sesion.patch(f"/api/tickets/{ticket['id']}", json={"prioridad": "baja"})
    assert r.status_code == 200
    assert r.json()["fecha_limite"] == "2026-03-05T09:00:00Z"


def test_la_reclasificacion_recalcula_el_plazo(sesion, llm):
    ticket = nuevo_por_api(sesion)
    llm.contenido = '{"categoria": "tecnico", "prioridad": "alta", "justificacion": "Urgente."}'
    r = sesion.post(f"/api/tickets/{ticket['id']}/reclasificar")
    assert r.status_code == 200
    assert r.json()["fecha_limite"] == "2026-03-02T13:00:00Z"


def test_los_tickets_anteriores_sin_plazo_reciben_su_fecha_limite(db, crear):
    antiguo = crear("Antiguo", prioridad="baja", fecha_limite=None)
    con_plazo = crear("Con plazo", fecha_limite="2030-01-01T00:00:00Z")
    assert sla.rellenar_fechas_limite(db) == 1
    assert fila(db, antiguo)["fecha_limite"] == "2026-03-05T09:00:00Z"
    assert fila(db, con_plazo)["fecha_limite"] == "2030-01-01T00:00:00Z"


# --- bandeja ---


def test_la_bandeja_marca_vencidos_y_muestra_el_tiempo_excedido(sesion, crear, reloj):
    crear("Atrasado", prioridad="alta")
    reloj.avanzar(hours=6)
    texto = sesion.get("/bandeja").text
    assert '<span class="etiqueta etiqueta-vencido">Vencido</span>' in texto
    assert "Excedido por 2 h" in texto


def test_la_bandeja_muestra_el_tiempo_restante_sin_etiqueta_vencido(sesion, crear, reloj):
    crear("A tiempo", prioridad="alta")
    reloj.avanzar(hours=1)
    texto = sesion.get("/bandeja").text
    assert "Quedan 3 h" in texto
    assert "etiqueta-vencido" not in texto


def test_la_bandeja_no_muestra_plazo_en_tickets_resueltos_o_cerrados(sesion, crear, reloj):
    crear("Hecho", estado="resuelto", prioridad="alta")
    crear("Cerrado", estado="cerrado", prioridad="alta")
    reloj.avanzar(days=3)
    texto = sesion.get("/bandeja").text
    assert "etiqueta-vencido" not in texto
    assert "Excedido" not in texto
    assert "Quedan" not in texto


def test_el_filtro_solo_vencidos_deja_unicamente_los_vencidos(sesion, crear, reloj):
    crear("Vencido alta", prioridad="alta")
    crear("Vencido en curso", estado="en_curso", prioridad="alta")
    crear("En plazo baja", prioridad="baja")
    crear("Resuelto vencido", estado="resuelto", prioridad="alta")
    crear("Cerrado vencido", estado="cerrado", prioridad="alta")
    crear("Sin plazo", fecha_limite=None)
    reloj.avanzar(hours=5)
    assert len(asuntos(sesion.get("/bandeja"))) == 6
    con_filtro = sesion.get("/bandeja?vencidos=1")
    assert sorted(asuntos(con_filtro)) == ["Vencido alta", "Vencido en curso"]
    assert "2 tickets con los filtros aplicados" in " ".join(con_filtro.text.split())


def test_el_filtro_usa_el_reloj_inyectado(sesion, crear, reloj):
    crear("Media", prioridad="media")
    assert asuntos(sesion.get("/bandeja?vencidos=1")) == []
    reloj.avanzar(hours=24)
    assert asuntos(sesion.get("/bandeja?vencidos=1")) == []
    reloj.avanzar(seconds=1)
    assert asuntos(sesion.get("/bandeja?vencidos=1")) == ["Media"]


def test_el_filtro_se_combina_con_los_demas(sesion, crear, reloj):
    crear("Alta vencida", prioridad="alta")
    crear("Media vencida", prioridad="media", creado="2026-03-01T00:00:00Z")
    reloj.avanzar(hours=5)
    assert asuntos(sesion.get("/bandeja?vencidos=1&prioridad=media")) == ["Media vencida"]


def test_el_filtro_funciona_con_htmx_y_se_conserva_en_la_paginacion(sesion, crear, reloj):
    for numero in range(30):
        crear(f"Vencido {numero}", prioridad="alta")
    reloj.avanzar(hours=5)
    r = sesion.get("/bandeja?vencidos=1", headers=HX)
    assert "<html" not in r.text
    assert len(asuntos(r)) == 25
    assert "vencidos=1&amp;page=2" in r.text or "vencidos=1&page=2" in r.text


def test_la_casilla_solo_vencidos_refleja_el_filtro(sesion):
    sin = sesion.get("/bandeja").text
    assert "Solo vencidos" in sin
    assert 'name="vencidos" type="checkbox" value="1">' in sin
    con = sesion.get("/bandeja?vencidos=1").text
    assert 'name="vencidos" type="checkbox" value="1" checked>' in con


def test_un_valor_raro_en_vencidos_equivale_a_sin_filtro(sesion, crear):
    crear("Uno", prioridad="baja")
    assert asuntos(sesion.get("/bandeja?vencidos=quizas")) == ["Uno"]


# --- detalle ---


def test_el_detalle_muestra_vencido_y_el_tiempo_excedido(sesion, crear, reloj):
    ticket_id = crear(prioridad="alta")
    reloj.avanzar(hours=4, minutes=30)
    texto = sesion.get(f"/tickets/{ticket_id}").text
    assert "Vencido</span>" in texto
    assert "Excedido por 30 min" in texto
    assert "02/03/2026 13:00 UTC" in texto


def test_el_detalle_muestra_el_tiempo_restante(sesion, crear, reloj):
    ticket_id = crear(prioridad="baja")
    reloj.avanzar(hours=2)
    texto = sesion.get(f"/tickets/{ticket_id}").text
    assert "Quedan 2 d 22 h" in texto
    assert "etiqueta-vencido" not in texto


def test_resolver_el_ticket_quita_la_etiqueta_vencido(sesion, crear, reloj):
    ticket_id = crear(prioridad="alta")
    reloj.avanzar(hours=10)
    assert "Vencido</span>" in sesion.get(f"/tickets/{ticket_id}").text
    r = sesion.post(f"/tickets/{ticket_id}/estado", data={"estado": "resuelto"}, headers=HX)
    assert r.status_code == 200
    assert "Vencido</span>" not in r.text
    assert "Excedido" not in r.text


def test_cambiar_la_prioridad_en_el_detalle_actualiza_el_plazo_mostrado(sesion, crear, reloj):
    ticket_id = crear(prioridad="alta")
    reloj.avanzar(hours=6)
    assert "Vencido</span>" in sesion.get(f"/tickets/{ticket_id}").text
    r = sesion.post(f"/tickets/{ticket_id}/clasificacion", data={"prioridad": "baja"}, headers=HX)
    assert r.status_code == 200
    assert 'hx-swap-oob="true"' in r.text
    assert "05/03/2026 09:00 UTC" in r.text
    assert "Quedan 2 d 18 h" in r.text
    assert "Vencido</span>" not in r.text


def test_un_ticket_sin_plazo_muestra_sin_plazo_definido(sesion, crear):
    ticket_id = crear(fecha_limite=None)
    texto = sesion.get(f"/tickets/{ticket_id}").text
    assert "Sin plazo definido" in texto
    assert "Vencido</span>" not in texto
