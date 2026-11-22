import re

from app.services.graficos import ANCHO_BARRA_MAX, barras_svg


def _anchos(svg: str) -> list[float]:
    return [float(x) for x in re.findall(r'<rect class="grafico-barra"[^>]* width="([\d.]+)"', svg)]


def test_una_barra_por_dato_con_su_valor_escrito():
    svg = str(barras_svg([("Nuevo", 3), ("Cerrado", 6)], "Por estado"))
    assert svg.startswith("<svg")
    assert svg.count('class="grafico-barra"') == 2
    assert ">Nuevo</text>" in svg and ">Cerrado</text>" in svg
    assert re.findall(r'class="grafico-valor"[^>]*>(\d+)</text>', svg) == ["3", "6"]


def test_las_barras_son_proporcionales_al_maximo():
    anchos = _anchos(str(barras_svg([("A", 2), ("B", 4), ("C", 0)], "T")))
    assert anchos == [ANCHO_BARRA_MAX / 2, ANCHO_BARRA_MAX, 0]


def test_todo_a_cero_no_divide_por_cero():
    svg = str(barras_svg([("A", 0), ("B", 0)], "T"))
    assert _anchos(svg) == [0, 0]
    assert svg.count('class="grafico-valor"') == 2


def test_sin_datos_devuelve_svg_valido():
    svg = str(barras_svg([], "Vacío"))
    assert svg.startswith("<svg") and svg.endswith("</svg>")


def test_escapa_etiquetas_y_titulo():
    svg = str(barras_svg([("<script>x</script>", 1)], 'Tít"ulo <b>'))
    assert "<script>" not in svg and "<b>" not in svg
    assert "&lt;script&gt;" in svg


def test_no_usa_javascript():
    assert "<script" not in str(barras_svg([("A", 1)], "T"))
