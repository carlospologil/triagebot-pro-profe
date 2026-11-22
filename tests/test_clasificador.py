import logging
from types import SimpleNamespace

import pytest
from fastapi import Request

from app.config import Settings
from app.services import clasificador
from app.services.clasificador import (
    ClasificacionError,
    ClasificacionIA,
    clasificar,
    get_cliente_llm,
)
from app.services.usuarios import create_user
from tests.conftest import FalsoLLM

PASSWORD = "una-clave-segura"


@pytest.fixture
def sesion(client, db):
    usuario = create_user(db, email="agente@example.com", nombre="Ana", password=PASSWORD)
    r = client.post(
        "/login", data={"email": usuario.email, "password": PASSWORD}, follow_redirects=False
    )
    assert r.status_code == 303
    return client


def crear(client, **extra):
    datos = {
        "asunto": "Cobro duplicado",
        "texto": "Me han cobrado dos veces",
        "email_cliente": "c@example.com",
        **extra,
    }
    r = client.post("/api/tickets", json=datos)
    assert r.status_code == 201, r.text
    return r.json()


def json_llm(categoria="facturacion", prioridad="alta", justificacion="Cobro duplicado."):
    return (
        f'{{"categoria": "{categoria}", "prioridad": "{prioridad}", '
        f'"justificacion": "{justificacion}"}}'
    )


# --- función clasificar (unitarios) ---


def test_clasificar_respuesta_valida():
    llm = FalsoLLM(json_llm("envio", "baja", "Paquete retrasado."))
    r = clasificar(llm, "Mi paquete", "No llega")
    assert r == ClasificacionIA(
        categoria="envio", prioridad="baja", justificacion="Paquete retrasado."
    )


def test_clasificar_pide_json_con_timeout_de_20_segundos():
    llm = FalsoLLM()
    clasificar(llm, "Asunto", "Texto")
    (llamada,) = llm.llamadas
    assert llamada["model"] == "openai/gpt-oss-120b"
    assert llamada["response_format"] == {"type": "json_object"}
    assert llamada["timeout"] == 20
    assert "Asunto" in llamada["messages"][1]["content"]


@pytest.mark.parametrize(
    "contenido",
    [
        "esto no es json",
        "",
        None,
        "[]",
        '{"categoria": "facturacion"}',
        json_llm(categoria="comercial"),
        json_llm(prioridad="urgente"),
        json_llm(justificacion="   "),
    ],
)
def test_clasificar_respuesta_invalida_lanza_error(contenido):
    with pytest.raises(ClasificacionError):
        clasificar(FalsoLLM(contenido), "a", "t")


def test_clasificar_excepcion_del_cliente_lanza_error():
    with pytest.raises(ClasificacionError, match="TimeoutError"):
        clasificar(FalsoLLM(error=TimeoutError("agotado")), "a", "t")


def test_clasificar_sin_cliente_lanza_error():
    with pytest.raises(ClasificacionError, match="OPENROUTER_API_KEY"):
        clasificar(None, "a", "t")


def test_clasificar_trunca_textos_largos():
    llm = FalsoLLM()
    clasificar(llm, "a", "x" * 20000)
    assert len(llm.llamadas[0]["messages"][1]["content"]) < 5000


# --- alta de ticket ---


def test_crear_guarda_categoria_prioridad_y_justificacion(sesion, llm):
    llm.contenido = json_llm("facturacion", "alta", "Cobro duplicado.")
    t = crear(sesion)
    assert (t["categoria"], t["prioridad"], t["resumen_ia"]) == (
        "facturacion",
        "alta",
        "Cobro duplicado.",
    )
    assert sesion.get(f"/api/tickets/{t['id']}").json() == t
    assert len(llm.llamadas) == 1


def test_crear_con_json_invalido_crea_sin_clasificar_y_registra_el_error(sesion, llm, caplog):
    llm.contenido = "no es json"
    with caplog.at_level(logging.ERROR, logger="app.services.tickets"):
        t = crear(sesion)
    assert t["categoria"] == "sin_clasificar"
    assert t["prioridad"] == "media"
    assert t["resumen_ia"] is None
    assert any(f"ticket {t['id']}" in m and "ValidationError" in m for m in caplog.messages)


def test_crear_con_json_fuera_de_esquema_crea_sin_clasificar(sesion, llm):
    llm.contenido = json_llm(categoria="inventada")
    assert crear(sesion)["categoria"] == "sin_clasificar"


def test_crear_con_excepcion_crea_sin_clasificar_y_registra_el_error(sesion, llm, caplog):
    llm.error = TimeoutError("Request timed out.")
    with caplog.at_level(logging.ERROR, logger="app.services.tickets"):
        t = crear(sesion)
    assert t["categoria"] == "sin_clasificar"
    assert t["estado"] == "nuevo"
    assert any("Request timed out." in m for m in caplog.messages)
    assert sesion.get(f"/api/tickets/{t['id']}").json()["categoria"] == "sin_clasificar"


def test_crear_sin_cliente_configurado_crea_sin_clasificar(settings, reloj, db, caplog):
    from fastapi.testclient import TestClient

    from app.main import create_app

    create_user(db, email="agente@example.com", nombre="Ana", password=PASSWORD)
    with TestClient(create_app(settings, clock=reloj)) as c:  # sin override ni API key
        c.post("/login", data={"email": "agente@example.com", "password": PASSWORD})
        with caplog.at_level(logging.ERROR, logger="app.services.tickets"):
            t = crear(c)
    assert t["categoria"] == "sin_clasificar"
    assert any("OPENROUTER_API_KEY" in m for m in caplog.messages)


# --- reclasificar ---


def test_reclasificar_actualiza_la_clasificacion(sesion, llm, reloj):
    llm.error = RuntimeError("caído")
    t = crear(sesion)
    assert t["categoria"] == "sin_clasificar"

    llm.error = None
    llm.contenido = json_llm("tecnico", "alta", "Fallo del servicio.")
    reloj.avanzar(minutes=5)
    r = sesion.post(f"/api/tickets/{t['id']}/reclasificar")
    assert r.status_code == 200
    nuevo = r.json()
    assert (nuevo["categoria"], nuevo["prioridad"], nuevo["resumen_ia"]) == (
        "tecnico",
        "alta",
        "Fallo del servicio.",
    )
    assert nuevo["actualizado_en"] == "2026-03-02T09:05:00Z"
    assert nuevo["creado_en"] == t["creado_en"]
    assert sesion.get(f"/api/tickets/{t['id']}").json() == nuevo


def test_reclasificar_si_la_ia_falla_responde_502_y_no_toca_el_ticket(sesion, llm, caplog):
    llm.contenido = json_llm("cuenta", "baja", "Duda de acceso.")
    t = crear(sesion)
    llm.contenido = "basura"
    with caplog.at_level(logging.ERROR, logger="app.services.tickets"):
        r = sesion.post(f"/api/tickets/{t['id']}/reclasificar")
    assert r.status_code == 502
    assert caplog.messages
    assert sesion.get(f"/api/tickets/{t['id']}").json() == t


def test_reclasificar_ticket_inexistente_404(sesion):
    assert sesion.post("/api/tickets/999/reclasificar").status_code == 404


def test_reclasificar_sin_sesion_401(client):
    assert client.post("/api/tickets/1/reclasificar").status_code == 401


# --- cliente real (sin red) ---


def _peticion(settings: Settings):
    app = SimpleNamespace(state=SimpleNamespace(settings=settings))
    return Request({"type": "http", "app": app, "headers": []})


def test_get_cliente_llm_sin_clave_devuelve_none(settings):
    assert get_cliente_llm(_peticion(settings)) is None


def test_get_cliente_llm_configura_openrouter_y_reutiliza_el_cliente():
    ajustes = Settings(secret_key="x", openrouter_api_key="clave-falsa")
    peticion = _peticion(ajustes)
    cliente = get_cliente_llm(peticion)
    assert str(cliente.base_url).startswith("https://openrouter.ai/api/v1")
    assert cliente.timeout == clasificador.TIMEOUT_SEGUNDOS == 20
    assert get_cliente_llm(peticion) is cliente
