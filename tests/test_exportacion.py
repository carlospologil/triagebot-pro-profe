import csv
import io
from pathlib import Path

import pytest

from app.services import exportacion, importacion
from app.services.usuarios import create_user

FIXTURES = Path(__file__).parent / "fixtures"
PASSWORD = "una-clave-segura"


def _filas_csv(respuesta) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(respuesta.content.decode("utf-8-sig"))))


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


@pytest.fixture
def importados(db, reloj, llm):
    """Los tickets válidos de tests/fixtures/tickets.csv, sin clasificar."""
    filas = importacion.leer_filas(FIXTURES / "tickets.csv")
    importacion.importar_tickets(db, filas, llm, reloj, clasificar=False)


def test_exporta_igual_que_el_fichero_esperado(sesion, db, reloj, llm):
    filas = importacion.leer_filas(FIXTURES / "tickets.csv")[:2]
    importacion.importar_tickets(db, filas, llm, reloj, clasificar=False)
    r = sesion.get("/api/tickets/export.csv")
    assert r.status_code == 200
    esperado = (FIXTURES / "exportacion_esperada.csv").read_text(encoding="utf-8")
    assert list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")))) == list(
        csv.reader(io.StringIO(esperado))
    )


def test_cabeceras_y_codificacion_para_excel(sesion, importados):
    r = sesion.get("/api/tickets/export.csv")
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert r.headers["content-disposition"] == 'attachment; filename="tickets-2026-03-02.csv"'
    assert r.content.startswith(b"\xef\xbb\xbf")


def test_neutraliza_formulas(sesion, importados):
    textos = [f["texto"] for f in _filas_csv(sesion.get("/api/tickets/export.csv"))]
    assert '\'=HYPERLINK("http://ejemplo.invalid")' in textos
    assert not any(t.startswith("=") for t in textos)


def test_exporta_todo_sin_paginar(sesion, db, reloj, llm):
    filas = [{"texto": f"Ticket {n}"} for n in range(60)]
    importacion.importar_tickets(db, filas, llm, reloj, clasificar=False)
    assert len(_filas_csv(sesion.get("/api/tickets/export.csv"))) == 60


def test_sin_tickets_solo_hay_cabecera(sesion):
    r = sesion.get("/api/tickets/export.csv")
    assert r.status_code == 200
    assert _filas_csv(r) == []
    assert r.text.lstrip("﻿").startswith("id,asunto,texto,")


def test_respeta_los_filtros_de_la_bandeja(sesion, db, agente, importados):
    db.execute(
        "UPDATE tickets SET estado = 'en_curso', prioridad = 'alta', asignado_a = ? WHERE id = 1",
        (agente.id,),
    )
    db.commit()

    def ids(**params):
        return [f["id"] for f in _filas_csv(sesion.get("/api/tickets/export.csv", params=params))]

    assert ids(estado="en_curso") == ["1"]
    assert ids(prioridad="alta") == ["1"]
    assert ids(asignado_a=agente.id) == ["1"]
    assert ids(mios="1") == ["1"]
    assert ids(asignado_a="sin_asignar") == ["4", "3", "2"]
    assert ids(categoria="sin_clasificar", estado="nuevo") == ["4", "3", "2"]
    assert ids(q="cobraron") == ["2"]
    assert ids(q="ana@example.com") == ["1"]
    assert ids(estado="resuelto") == []


def test_solo_vencidos(sesion, db, reloj, importados):
    assert _filas_csv(sesion.get("/api/tickets/export.csv", params={"vencidos": "1"})) == []
    reloj.avanzar(days=30)
    r = sesion.get("/api/tickets/export.csv", params={"vencidos": "1"})
    assert len(_filas_csv(r)) == 4


def test_filtros_invalidos_equivalen_a_no_filtrar(sesion, importados):
    r = sesion.get("/api/tickets/export.csv", params={"estado": "inventado", "asignado_a": "x"})
    assert len(_filas_csv(r)) == 4


def test_incluye_el_nombre_del_asignado(sesion, db, agente, importados):
    db.execute("UPDATE tickets SET asignado_a = ? WHERE id = 1", (agente.id,))
    db.commit()
    filas = {f["id"]: f for f in _filas_csv(sesion.get("/api/tickets/export.csv"))}
    assert filas["1"]["asignado_a"] == "Ana"
    assert filas["2"]["asignado_a"] == ""


def test_exige_sesion(client):
    assert client.get("/api/tickets/export.csv").status_code == 401


def test_bandeja_tiene_boton_exportar_con_los_filtros_activos(sesion, importados):
    r = sesion.get("/bandeja")
    assert 'id="exportar"' in r.text
    assert 'href="/api/tickets/export.csv"' in r.text

    r = sesion.get("/bandeja?estado=nuevo&q=ana+b&vencidos=1&page=1")
    assert 'href="/api/tickets/export.csv?estado=nuevo&amp;vencidos=1&amp;q=ana+b"' in r.text


def test_el_boton_se_actualiza_con_la_tabla_htmx(sesion, importados):
    r = sesion.get("/bandeja?categoria=sin_clasificar", headers={"HX-Request": "true"})
    assert 'href="/api/tickets/export.csv?categoria=sin_clasificar"' in r.text
    assert "<html" not in r.text


def test_el_valor_de_celda_none_sale_vacio():
    class Fila(dict):
        pass

    fila = Fila({c: None for _, c in exportacion.COLUMNAS})
    salida = exportacion.tickets_a_csv([fila])
    assert salida.splitlines()[-1] == "," * (len(exportacion.COLUMNAS) - 1)
