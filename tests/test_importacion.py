from pathlib import Path

import pytest

from app.services import importacion
from app.services.clasificador import CATEGORIA_SIN_CLASIFICAR
from tests.conftest import FalsoLLM

FIXTURES = Path(__file__).parent / "fixtures"


def _tickets(db):
    return db.execute("SELECT * FROM tickets ORDER BY id").fetchall()


def test_csv_importa_y_salta_las_filas_invalidas(db, reloj, llm):
    filas = importacion.leer_filas(FIXTURES / "tickets.csv")
    resultado = importacion.importar_tickets(db, filas, llm, reloj)
    assert resultado.importados == 4
    assert resultado.saltados == [
        "Fila 3: sin texto",
        "Fila 6: valor no válido en «email_cliente»",
    ]
    t1, t2, t3, t4 = _tickets(db)
    assert (t1["asunto"], t1["solicitante_email"]) == ("Acceso bloqueado", "ana@example.com")
    assert t2["solicitante_email"] == "luis@example.com"
    assert t2["descripcion"] == "Me cobraron dos veces\nesta factura"
    assert t3["asunto"] == "Solo tengo texto"
    assert t3["solicitante_email"] == importacion.EMAIL_DESCONOCIDO
    assert t3["solicitante_nombre"] == importacion.NOMBRE_DESCONOCIDO
    assert t4["descripcion"].startswith("=HYPERLINK")


def test_csv_clasifica_cada_ticket_importado(db, reloj, llm):
    filas = importacion.leer_filas(FIXTURES / "tickets.csv")
    importacion.importar_tickets(db, filas, llm, reloj)
    assert len(llm.llamadas) == 4
    assert {t["categoria"] for t in _tickets(db)} == {"otro"}
    assert {t["resumen_ia"] for t in _tickets(db)} == {"Consulta general."}


def test_json_importa_y_salta(db, reloj, llm):
    filas = importacion.leer_filas(FIXTURES / "tickets.json")
    resultado = importacion.importar_tickets(db, filas, llm, reloj)
    assert resultado.importados == 2
    assert resultado.saltados == [
        "Fila 2: sin texto",
        "Fila 3: sin texto",
        "Fila 4: no es un objeto",
    ]
    primero, segundo = _tickets(db)
    assert primero["asunto"] == "Pedido retrasado"
    assert primero["solicitante_email"] == "eva@example.com"
    assert segundo["asunto"] == "Quiero cambiar mi plan"


@pytest.mark.parametrize("fichero", ["tickets.csv", "tickets.json"])
def test_sin_clasificar_no_llama_al_llm(db, reloj, llm, fichero):
    filas = importacion.leer_filas(FIXTURES / fichero)
    resultado = importacion.importar_tickets(db, filas, llm, reloj, clasificar=False)
    assert llm.llamadas == []
    assert resultado.importados == len(_tickets(db)) > 0
    assert {t["categoria"] for t in _tickets(db)} == {CATEGORIA_SIN_CLASIFICAR}


def test_si_la_ia_falla_el_ticket_queda_sin_clasificar(db, reloj):
    llm = FalsoLLM(error=RuntimeError("caído"))
    filas = importacion.leer_filas(FIXTURES / "tickets.json")
    resultado = importacion.importar_tickets(db, filas, llm, reloj)
    assert (resultado.importados, resultado.sin_clasificar) == (2, 2)
    assert {t["categoria"] for t in _tickets(db)} == {CATEGORIA_SIN_CLASIFICAR}


def test_csv_con_bom_punto_y_coma_y_cabeceras_en_mayusculas(tmp_path):
    ruta = tmp_path / "excel.csv"
    ruta.write_text("Texto;Asunto\nHola;Saludo\n", encoding="utf-8-sig")
    assert importacion.leer_filas(ruta) == [{"texto": "Hola", "asunto": "Saludo"}]


def test_las_filas_totalmente_vacias_se_ignoran(tmp_path):
    ruta = tmp_path / "huecos.csv"
    ruta.write_text("texto\nuno\n\n,\ndos\n", encoding="utf-8")
    assert [f["texto"] for f in importacion.leer_filas(ruta)] == ["uno", "dos"]


def test_asunto_automatico_se_trunca(db, reloj, llm):
    texto = "palabra " * 30
    resultado = importacion.importar_tickets(db, [{"texto": texto}], llm, reloj, clasificar=False)
    assert resultado.importados == 1
    asunto = _tickets(db)[0]["asunto"]
    assert len(asunto) == importacion.MAX_ASUNTO_AUTOMATICO
    assert asunto.endswith("…")


@pytest.mark.parametrize(
    ("nombre", "contenido", "mensaje"),
    [
        ("sin_columna.csv", "asunto\nHola\n", "columna «texto»"),
        ("vacio.csv", "", "columna «texto»"),
        ("roto.json", "[{", "JSON no válido"),
        ("objeto.json", '{"texto": "x"}', "lista de objetos"),
        ("datos.xlsx", "x", "Formato no admitido"),
    ],
)
def test_ficheros_invalidos(tmp_path, nombre, contenido, mensaje):
    ruta = tmp_path / nombre
    ruta.write_text(contenido, encoding="utf-8")
    with pytest.raises(importacion.ImportacionError, match=mensaje):
        importacion.leer_filas(ruta)


def test_fichero_inexistente(tmp_path):
    with pytest.raises(importacion.ImportacionError, match="No existe"):
        importacion.leer_filas(tmp_path / "nada.csv")


def test_fichero_que_no_es_utf8(tmp_path):
    ruta = tmp_path / "latin.csv"
    ruta.write_bytes("texto\nñandú\n".encode("latin-1"))
    with pytest.raises(importacion.ImportacionError, match="UTF-8"):
        importacion.leer_filas(ruta)
