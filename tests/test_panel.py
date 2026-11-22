import re

import pytest

from tests.datos_metricas import PASSWORD, cargar_datos


@pytest.fixture
def datos(db):
    return cargar_datos(db)


def entrar(client, email):
    r = client.post("/login", data={"email": email, "password": PASSWORD}, follow_redirects=False)
    assert r.status_code == 303
    return client


def texto(html: str, id_: str) -> str:
    return re.search(rf'id="{id_}">([^<]*)<', html).group(1)


def valores_grafico(html: str, titulo: str) -> dict[str, str]:
    """Pares etiqueta -> valor del gráfico SVG de la tarjeta con ese título."""
    tarjeta = html.split(f"<h2>{titulo}</h2>")[1].split("</section>")[0]
    etiquetas = re.findall(r'class="grafico-etiqueta"[^>]*>([^<]*)</text>', tarjeta)
    valores = re.findall(r'class="grafico-valor"[^>]*>([^<]*)</text>', tarjeta)
    return dict(zip(etiquetas, valores, strict=True))


def test_panel_exige_sesion(client):
    r = client.get("/panel", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


@pytest.mark.parametrize("email", ["admin@example.com", "ana@example.com"])
def test_panel_disponible_para_cualquier_usuario_autenticado(client, datos, email):
    r = entrar(client, email).get("/panel")
    assert r.status_code == 200
    assert "Panel de métricas" in r.text


def test_panel_muestra_indicadores(client, datos):
    html = entrar(client, "admin@example.com").get("/panel").text
    assert texto(html, "total-tickets") == "9"
    assert texto(html, "tickets-vencidos") == "2"
    assert texto(html, "tiempo-medio") == "5,8 h"


def test_panel_muestra_totales_por_estado_categoria_y_prioridad(client, datos):
    html = entrar(client, "admin@example.com").get("/panel").text
    assert valores_grafico(html, "Tickets por estado") == {
        "Nuevo": "1",
        "En curso": "1",
        "Esperando al cliente": "1",
        "Resuelto": "5",
        "Cerrado": "1",
    }
    assert valores_grafico(html, "Tickets por categoría") == {
        "Facturación": "2",
        "Técnico": "2",
        "Cuenta": "1",
        "Comercial": "1",
        "Envío": "0",
        "Otro": "1",
        "Sin clasificar": "2",
    }
    assert valores_grafico(html, "Tickets por prioridad") == {
        "Baja": "3",
        "Media": "4",
        "Alta": "1",
        "Urgente": "1",
    }


def test_panel_muestra_resueltos_por_agente(client, datos):
    html = entrar(client, "admin@example.com").get("/panel").text
    assert valores_grafico(html, "Resueltos por agente (últimos 7 días)") == {
        "Ana": "2",
        "Luis": "2",
        "Eva": "0",
    }


def test_graficos_son_svg_del_servidor_sin_javascript_propio(client, datos):
    html = entrar(client, "admin@example.com").get("/panel").text
    assert html.count('<svg class="grafico"') == 4
    # Solo se carga HTMX (base.html); el panel no añade ningún otro script.
    assert re.findall(r"<script[^>]*src=\"([^\"]+)\"", html) == ["https://unpkg.com/htmx.org@2.0.4"]
    assert "<script>" not in html


def test_panel_sin_tickets_muestra_ceros_y_guion(client, db):
    from app.services.usuarios import create_user

    create_user(db, email="dir@example.com", nombre="Dir", password=PASSWORD, rol="admin")
    html = entrar(client, "dir@example.com").get("/panel").text
    assert texto(html, "total-tickets") == "0"
    assert texto(html, "tickets-vencidos") == "0"
    assert texto(html, "tiempo-medio") == "—"


def test_panel_usa_el_reloj_inyectado(client, datos, reloj):
    reloj.avanzar(hours=4)
    html = entrar(client, "admin@example.com").get("/panel").text
    assert texto(html, "tickets-vencidos") == "3"


def test_bandeja_enlaza_al_panel(client, datos):
    assert 'href="/panel"' in entrar(client, "ana@example.com").get("/bandeja").text
