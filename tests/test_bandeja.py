import re

import pytest

from app.services.usuarios import create_user

PASSWORD = "una-clave-segura"
HX = {"HX-Request": "true"}


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
        asunto,
        *,
        estado="nuevo",
        prioridad="media",
        categoria="otro",
        asignado_a=None,
        cliente="Laura",
        email="laura@example.com",
        texto="Texto",
        creado="2026-03-02T09:00:00Z",
    ):
        cursor = db.execute(
            "INSERT INTO tickets (asunto, descripcion, solicitante_nombre, solicitante_email, "
            "estado, prioridad, categoria, asignado_a, creado_en, actualizado_en) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (asunto, texto, cliente, email, estado, prioridad, categoria, asignado_a, creado,
             creado),
        )  # fmt: skip
        db.commit()
        return cursor.lastrowid

    return _crear


def asuntos(respuesta) -> list[str]:
    return re.findall(r'<td class="col-asunto"><a href="/tickets/\d+">([^<]*)</a>', respuesta.text)


# --- página completa ---


def test_raiz_y_bandeja_muestran_la_tabla(sesion, crear):
    crear("Factura duplicada")
    for ruta in ("/", "/bandeja"):
        r = sesion.get(ruta)
        assert r.status_code == 200
        assert "<html" in r.text
        assert '<table class="tabla-tickets">' in r.text
        assert "Factura duplicada" in r.text


def test_la_pagina_carga_htmx_desde_la_plantilla_base(sesion):
    r = sesion.get("/bandeja")
    assert '<script src="https://unpkg.com/htmx.org@2.0.4"' in r.text


def test_la_tabla_tiene_todas_las_columnas(sesion, crear):
    crear("Cualquiera")
    r = sesion.get("/bandeja")
    cabeceras = re.findall(r'<th scope="col">([^<]*)</th>', r.text)
    assert cabeceras == [
        "Asunto", "Cliente", "Categoría", "Prioridad", "Estado", "Asignado", "Antigüedad",
    ]  # fmt: skip


def test_la_fila_muestra_los_datos_del_ticket(sesion, crear, agente, reloj):
    ticket_id = crear(
        "No puedo entrar",
        cliente="Marta Pérez",
        categoria="cuenta",
        prioridad="alta",
        estado="en_curso",
        asignado_a=agente.id,
        creado="2026-03-02T06:00:00Z",
    )
    texto = sesion.get("/bandeja").text
    assert f'<a href="/tickets/{ticket_id}">No puedo entrar</a>' in texto
    assert "Marta Pérez" in texto
    assert "<td>Cuenta</td>" in texto
    assert "<td>Ana</td>" in texto
    assert "hace 3 h" in texto


def test_antiguedad_usa_el_reloj_inyectado(sesion, crear, reloj):
    crear("Antiguo", creado="2026-03-02T09:00:00Z")
    assert "hace un momento" in sesion.get("/bandeja").text
    reloj.avanzar(days=2)
    assert "hace 2 d" in sesion.get("/bandeja").text


def test_prioridad_y_estado_son_etiquetas_con_texto_y_color(sesion, crear):
    crear("Caída total", prioridad="urgente", estado="esperando_cliente")
    texto = sesion.get("/bandeja").text
    assert '<span class="etiqueta etiqueta-prioridad-urgente">Urgente</span>' in texto
    assert (
        '<span class="etiqueta etiqueta-estado-esperando_cliente">Esperando al cliente</span>'
        in texto
    )


@pytest.mark.parametrize("prioridad", ["baja", "media", "alta", "urgente"])
def test_cada_prioridad_lleva_su_clase_y_su_texto(sesion, crear, prioridad):
    crear("T", prioridad=prioridad)
    texto = sesion.get("/bandeja").text
    assert re.search(
        rf'etiqueta-prioridad-{prioridad}">{prioridad.capitalize()}</span>', texto
    )  # fmt: skip


@pytest.mark.parametrize(
    "estado", ["nuevo", "en_curso", "esperando_cliente", "resuelto", "cerrado"]
)
def test_cada_estado_lleva_su_clase_y_texto(sesion, crear, estado):
    crear("T", estado=estado)
    texto = sesion.get("/bandeja").text
    assert re.search(rf'etiqueta-estado-{estado}">[A-Za-zÁ-ú ]+</span>', texto)


def test_sin_asignar_y_sin_categoria(sesion, crear):
    crear("Huérfano", categoria=None)
    texto = sesion.get("/bandeja").text
    assert "Sin asignar" in texto
    assert "<td>Sin clasificar</td>" in texto


def test_bandeja_vacia(sesion):
    r = sesion.get("/bandeja")
    assert "Aún no hay tickets que mostrar." in r.text
    assert "<table" not in r.text


def test_se_escapa_el_html_del_asunto(sesion, crear):
    crear("<script>alert(1)</script>")
    texto = sesion.get("/bandeja").text
    assert "<script>alert(1)" not in texto
    assert "&lt;script&gt;" in texto


def test_orden_del_mas_reciente_al_mas_antiguo(sesion, crear):
    crear("Viejo", creado="2026-03-01T09:00:00Z")
    crear("Nuevo", creado="2026-03-02T08:00:00Z")
    assert asuntos(sesion.get("/bandeja")) == ["Nuevo", "Viejo"]


def test_sin_sesion_redirige_al_login(client):
    r = client.get("/bandeja", headers=HX, follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, "/login")


# --- filtros ---


@pytest.fixture
def surtido(crear, agente, otro):
    crear("A-facturacion-alta", categoria="facturacion", prioridad="alta", asignado_a=agente.id)
    crear("B-tecnico-baja", categoria="tecnico", prioridad="baja", asignado_a=otro.id,
          estado="resuelto")  # fmt: skip
    crear("C-sin-asignar", categoria="tecnico", prioridad="alta", estado="en_curso")


@pytest.mark.parametrize(
    ("consulta", "esperado"),
    [
        ("estado=resuelto", ["B-tecnico-baja"]),
        ("categoria=facturacion", ["A-facturacion-alta"]),
        ("prioridad=alta", ["C-sin-asignar", "A-facturacion-alta"]),
        ("categoria=tecnico&prioridad=alta", ["C-sin-asignar"]),
        ("asignado_a=sin_asignar", ["C-sin-asignar"]),
        ("estado=&categoria=&prioridad=&asignado_a=&q=", ["C-sin-asignar", "B-tecnico-baja",
                                                          "A-facturacion-alta"]),
        ("estado=inventado&prioridad=zzz&asignado_a=abc&page=x", ["C-sin-asignar",
                                                                  "B-tecnico-baja",
                                                                  "A-facturacion-alta"]),
    ],
)  # fmt: skip
def test_filtros_en_pagina_completa(sesion, surtido, consulta, esperado):
    assert asuntos(sesion.get(f"/bandeja?{consulta}")) == esperado


def test_filtrar_por_asignado(sesion, surtido, otro):
    assert asuntos(sesion.get(f"/bandeja?asignado_a={otro.id}")) == ["B-tecnico-baja"]


def test_solo_mios_filtra_por_el_usuario_de_la_sesion(sesion, surtido):
    assert asuntos(sesion.get("/bandeja?mios=1")) == ["A-facturacion-alta"]


def test_solo_mios_prevalece_sobre_asignado(sesion, surtido, otro):
    assert asuntos(sesion.get(f"/bandeja?mios=1&asignado_a={otro.id}")) == ["A-facturacion-alta"]


def test_buscador_mira_asunto_texto_y_cliente(sesion, crear):
    crear("Error al pagar", texto="Sale un 500", cliente="Iván", email="ivan@acme.es")
    crear("Otra cosa", texto="nada", cliente="Zoe", email="zoe@example.com")
    assert asuntos(sesion.get("/bandeja?q=pagar")) == ["Error al pagar"]
    assert asuntos(sesion.get("/bandeja?q=500")) == ["Error al pagar"]
    assert asuntos(sesion.get("/bandeja?q=acme")) == ["Error al pagar"]
    assert asuntos(sesion.get("/bandeja?q=zoe")) == ["Otra cosa"]


def test_buscador_trata_el_porcentaje_como_texto(sesion, crear):
    crear("Descuento 100% aplicado")
    crear("Otro")
    assert asuntos(sesion.get("/bandeja?q=%25")) == ["Descuento 100% aplicado"]


def test_sin_resultados_con_filtros(sesion, surtido):
    r = sesion.get("/bandeja?q=noexiste")
    assert "Ningún ticket coincide con los filtros." in r.text
    assert "0 tickets con los filtros aplicados" in re.sub(r"\s+", " ", r.text)


def test_los_controles_conservan_los_filtros_aplicados(sesion, surtido, agente):
    r = sesion.get(f"/bandeja?estado=resuelto&prioridad=baja&q=hola&mios=1&asignado_a={agente.id}")
    assert re.search(r'<option value="resuelto" selected>', r.text)
    assert re.search(r'<option value="baja" selected>', r.text)
    assert 'value="hola"' in r.text
    assert re.search(r'id="mios"[^>]*checked', r.text)


@pytest.mark.parametrize(
    "valor", ["99999999999999999999", str(2**63), "-1", "0", "9" * 400]
)  # fmt: skip
def test_un_asignado_numerico_fuera_de_rango_se_ignora_sin_error(sesion, surtido, valor):
    for cabeceras in ({}, HX):
        r = sesion.get(f"/bandeja?asignado_a={valor}", headers=cabeceras)
        assert r.status_code == 200
        assert len(asuntos(r)) == 3


def test_un_page_enorme_no_da_error(sesion, surtido):
    r = sesion.get(f"/bandeja?page={'9' * 30}")
    assert r.status_code == 200
    assert len(asuntos(r)) == 3


def test_el_asignado_con_ceros_a_la_izquierda_marca_la_opcion_del_select(sesion, surtido, otro):
    r = sesion.get(f"/bandeja?asignado_a=0{otro.id}")
    assert asuntos(r) == ["B-tecnico-baja"]
    assert f'<option value="{otro.id}" selected>Luis</option>' in r.text


def test_los_enlaces_de_paginacion_normalizan_el_asignado(sesion, crear, otro):
    for i in range(30):
        crear(f"T{i}", asignado_a=otro.id)
    r = sesion.get(f"/bandeja?asignado_a=0{otro.id}")
    assert f'hx-get="/bandeja?asignado_a={otro.id}&amp;page=2"' in r.text


def test_la_restauracion_del_historial_devuelve_la_pagina_completa(sesion, surtido):
    cabeceras = {**HX, "HX-History-Restore-Request": "true"}
    r = sesion.get("/bandeja?prioridad=alta", headers=cabeceras)
    assert r.status_code == 200
    assert "<html" in r.text
    assert 'id="filtros"' in r.text
    assert asuntos(r) == ["C-sin-asignar", "A-facturacion-alta"]


def test_una_peticion_htmx_normal_sigue_devolviendo_el_fragmento(sesion, surtido):
    r = sesion.get("/bandeja", headers={**HX, "HX-History-Restore-Request": "false"})
    assert "<html" not in r.text


def test_el_selector_de_asignado_lista_solo_usuarios_activos(sesion, db, otro):
    db.execute("UPDATE usuarios SET activo = 0 WHERE id = ?", (otro.id,))
    db.commit()
    r = sesion.get("/bandeja")
    assert ">Ana</option>" in r.text
    assert ">Luis</option>" not in r.text


# --- fragmento HTMX ---


def test_el_formulario_de_filtros_actualiza_solo_la_tabla_con_htmx(sesion):
    texto = sesion.get("/bandeja").text
    assert 'hx-get="/bandeja"' in texto
    assert 'hx-target="#tabla-tickets"' in texto
    assert 'id="tabla-tickets"' in texto
    assert "input changed delay:300ms from:#q" in texto


def test_el_fragmento_no_incluye_la_pagina_completa(sesion, crear):
    crear("Factura duplicada")
    r = sesion.get("/bandeja", headers=HX)
    assert r.status_code == 200
    assert "<html" not in r.text
    assert 'id="filtros"' not in r.text
    assert '<table class="tabla-tickets">' in r.text
    assert "Factura duplicada" in r.text
    assert "HX-Request" in r.headers["vary"]


def test_el_fragmento_aplica_los_filtros(sesion, surtido):
    r = sesion.get("/bandeja?categoria=tecnico&prioridad=alta&estado=en_curso", headers=HX)
    assert "<html" not in r.text
    assert asuntos(r) == ["C-sin-asignar"]
    assert "1 ticket con los filtros aplicados" in re.sub(r"\s+", " ", r.text)


def test_el_fragmento_aplica_solo_mios_y_buscador(sesion, surtido):
    assert asuntos(sesion.get("/bandeja?mios=1", headers=HX)) == ["A-facturacion-alta"]
    assert asuntos(sesion.get("/bandeja?q=sin-asignar", headers=HX)) == ["C-sin-asignar"]


def test_sin_cabecera_htmx_la_misma_url_devuelve_la_pagina_completa(sesion, surtido):
    r = sesion.get("/bandeja?prioridad=alta")
    assert "<html" in r.text
    assert asuntos(r) == ["C-sin-asignar", "A-facturacion-alta"]


# --- paginación ---


@pytest.fixture
def sesenta(crear):
    for i in range(60):
        crear(f"T{i:02d}", creado=f"2026-03-01T{i // 60:02d}:{i % 60:02d}:00Z")


def test_paginacion_de_25_en_25(sesion, sesenta):
    p1 = sesion.get("/bandeja")
    p2 = sesion.get("/bandeja?page=2")
    p3 = sesion.get("/bandeja?page=3")
    assert [len(asuntos(p)) for p in (p1, p2, p3)] == [25, 25, 10]
    assert asuntos(p1)[0] == "T59"
    assert asuntos(p2)[0] == "T34"
    assert asuntos(p3)[-1] == "T00"
    assert "Página 1 de 3" in p1.text and "60 tickets" in p1.text


def test_los_enlaces_de_paginacion_usan_htmx_y_conservan_filtros(sesion, sesenta):
    r = sesion.get("/bandeja?prioridad=media&q=T&page=2")
    for destino in ("1", "3"):
        enlace = f"/bandeja?prioridad=media&amp;q=T&amp;page={destino}"
        assert f'href="{enlace}"' in r.text
        assert f'hx-get="{enlace}"' in r.text
    assert 'hx-target="#tabla-tickets"' in r.text
    assert 'hx-push-url="true"' in r.text


def test_primera_y_ultima_pagina_desactivan_el_boton_correspondiente(sesion, sesenta):
    p1 = sesion.get("/bandeja").text
    p3 = sesion.get("/bandeja?page=3").text
    desactivado = '<span class="boton boton-secundario boton-desactivado" aria-disabled="true">'
    assert f"{desactivado}Anterior" in p1
    assert 'hx-get="/bandeja?page=2"' in p1
    assert f"{desactivado}Siguiente" in p3


def test_el_fragmento_tambien_pagina(sesion, sesenta):
    r = sesion.get("/bandeja?page=2", headers=HX)
    assert "<html" not in r.text
    assert len(asuntos(r)) == 25
    assert "Página 2 de 3" in r.text


def test_una_pagina_fuera_de_rango_se_ajusta_a_la_ultima(sesion, sesenta):
    r = sesion.get("/bandeja?page=99")
    assert "Página 3 de 3" in r.text
    assert len(asuntos(r)) == 10
    assert len(asuntos(sesion.get("/bandeja?page=0"))) == 25


def test_con_25_tickets_o_menos_no_hay_paginacion(sesion, crear):
    for i in range(25):
        crear(f"T{i}")
    r = sesion.get("/bandeja")
    assert len(asuntos(r)) == 25
    assert "paginacion" not in r.text
