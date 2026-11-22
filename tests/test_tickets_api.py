import pytest

from app.services.usuarios import create_user

PASSWORD = "una-clave-segura"


@pytest.fixture
def agente(db):
    return create_user(db, email="agente@example.com", nombre="Ana", password=PASSWORD)


@pytest.fixture
def otro_agente(db):
    return create_user(db, email="otro@example.com", nombre="Luis", password=PASSWORD)


@pytest.fixture
def sesion(client, agente):
    r = client.post(
        "/login", data={"email": agente.email, "password": PASSWORD}, follow_redirects=False
    )
    assert r.status_code == 303
    return client


def nuevo(client, asunto="Error al facturar", texto="No sale el PDF", **extra):
    datos = {"asunto": asunto, "texto": texto, "email_cliente": "cliente@example.com", **extra}
    r = client.post("/api/tickets", json=datos)
    assert r.status_code == 201, r.text
    return r.json()


def ids(respuesta):
    return [t["id"] for t in respuesta.json()["items"]]


# --- acceso ---


@pytest.mark.parametrize(
    ("metodo", "ruta"),
    [("post", "/api/tickets"), ("get", "/api/tickets"), ("get", "/api/tickets/1"),
     ("patch", "/api/tickets/1")],
)  # fmt: skip
def test_sin_sesion_la_api_responde_401(client, metodo, ruta):
    r = getattr(client, metodo)(ruta)
    assert r.status_code == 401


# --- POST ---


def test_crear_devuelve_201_con_el_ticket_en_estado_nuevo(sesion, reloj):
    r = sesion.post(
        "/api/tickets",
        json={
            "asunto": "  No puedo entrar ",
            "texto": "Sale error 500",
            "email_cliente": "Cliente@Example.com ",
            "nombre_cliente": "Laura",
        },
    )
    assert r.status_code == 201
    t = r.json()
    assert t["id"] >= 1
    assert t["estado"] == "nuevo"
    assert t["prioridad"] == "media"
    assert t["categoria"] == "otro"  # clasificada por el LLM falso de conftest (F07)
    assert t["asignado_a"] is None
    assert t["asunto"] == "No puedo entrar"
    assert t["texto"] == "Sale error 500"
    assert t["email_cliente"] == "cliente@example.com"
    assert t["nombre_cliente"] == "Laura"
    assert t["creado_en"] == t["actualizado_en"] == "2026-03-02T09:00:00Z"
    assert sesion.get(f"/api/tickets/{t['id']}").json() == t


def test_crear_sin_nombre_usa_el_email(sesion):
    assert nuevo(sesion)["nombre_cliente"] == "cliente@example.com"


@pytest.mark.parametrize(
    "datos",
    [
        {"texto": "x", "email_cliente": "a@b.es"},
        {"asunto": "x", "email_cliente": "a@b.es"},
        {"asunto": "x", "texto": "x"},
        {"asunto": "   ", "texto": "x", "email_cliente": "a@b.es"},
        {"asunto": "x", "texto": "", "email_cliente": "a@b.es"},
        {"asunto": "x" * 201, "texto": "x", "email_cliente": "a@b.es"},
        {"asunto": "x", "texto": "x", "email_cliente": "no-es-un-email"},
        {"asunto": "x", "texto": "x", "email_cliente": "a@b"},
    ],
)
def test_crear_con_datos_invalidos_da_422(sesion, datos):
    assert sesion.post("/api/tickets", json=datos).status_code == 422


# --- GET detalle ---


def test_detalle_devuelve_el_ticket(sesion):
    t = nuevo(sesion)
    r = sesion.get(f"/api/tickets/{t['id']}")
    assert (r.status_code, r.json()) == (200, t)


def test_detalle_inexistente_da_404(sesion):
    r = sesion.get("/api/tickets/999")
    assert r.status_code == 404


def test_detalle_con_id_no_numerico_da_422(sesion):
    assert sesion.get("/api/tickets/abc").status_code == 422


# --- GET listado: paginación ---


def test_listado_vacio(sesion):
    r = sesion.get("/api/tickets")
    assert r.json() == {"items": [], "total": 0, "page": 1, "page_size": 20, "paginas": 0}


def test_listado_ordena_del_mas_reciente_al_mas_antiguo(sesion, reloj):
    creados = []
    for i in range(3):
        creados.append(nuevo(sesion, asunto=f"T{i}")["id"])
        reloj.avanzar(minutes=1)
    assert ids(sesion.get("/api/tickets")) == creados[::-1]


def test_paginacion(sesion):
    creados = [nuevo(sesion, asunto=f"T{i}")["id"] for i in range(5)]
    esperado = creados[::-1]

    p1 = sesion.get("/api/tickets", params={"page": 1, "page_size": 2}).json()
    assert (p1["total"], p1["page"], p1["page_size"], p1["paginas"]) == (5, 1, 2, 3)
    assert [t["id"] for t in p1["items"]] == esperado[0:2]

    p2 = sesion.get("/api/tickets", params={"page": 2, "page_size": 2}).json()
    assert [t["id"] for t in p2["items"]] == esperado[2:4]

    p3 = sesion.get("/api/tickets", params={"page": 3, "page_size": 2}).json()
    assert [t["id"] for t in p3["items"]] == esperado[4:5]

    p4 = sesion.get("/api/tickets", params={"page": 4, "page_size": 2}).json()
    assert (p4["items"], p4["total"]) == ([], 5)


def test_page_size_maximo_100(sesion):
    assert sesion.get("/api/tickets", params={"page_size": 100}).status_code == 200
    assert sesion.get("/api/tickets", params={"page_size": 101}).status_code == 422


def test_page_size_100_devuelve_hasta_100(sesion, db):
    for i in range(101):
        db.execute(
            "INSERT INTO tickets (asunto, descripcion, solicitante_nombre, solicitante_email, "
            "creado_en, actualizado_en) VALUES (?, 'x', 'n', 'n@e.es', 't', 't')",
            (f"T{i}",),
        )
    db.commit()
    d = sesion.get("/api/tickets", params={"page_size": 100}).json()
    assert (len(d["items"]), d["total"], d["paginas"]) == (100, 101, 2)


@pytest.mark.parametrize(
    "params",
    [{"page": 0}, {"page": -1}, {"page_size": 0}, {"page_size": -5}, {"page": "x"}],
)
def test_paginacion_invalida_da_422(sesion, params):
    assert sesion.get("/api/tickets", params=params).status_code == 422


# --- GET listado: filtros ---


def preparar(sesion, agente, otro_agente):
    t1 = nuevo(sesion, asunto="Factura duplicada", texto="Cobro doble en marzo")
    t2 = nuevo(sesion, asunto="Fallo de login", texto="No recuerdo la contraseña")
    t3 = nuevo(sesion, asunto="Pedido retrasado", texto="Llega tarde la factura")
    sesion.patch(
        f"/api/tickets/{t1['id']}",
        json={"estado": "en_curso", "prioridad": "alta", "categoria": "facturacion",
              "asignado_a": agente.id},
    )  # fmt: skip
    sesion.patch(
        f"/api/tickets/{t2['id']}",
        json={"estado": "resuelto", "prioridad": "urgente", "categoria": "cuenta",
              "asignado_a": otro_agente.id},
    )  # fmt: skip
    sesion.patch(f"/api/tickets/{t3['id']}", json={"categoria": "facturacion"})
    return t1["id"], t2["id"], t3["id"]


def test_filtro_por_estado(sesion, agente, otro_agente):
    t1, t2, t3 = preparar(sesion, agente, otro_agente)
    assert ids(sesion.get("/api/tickets", params={"estado": "en_curso"})) == [t1]
    assert ids(sesion.get("/api/tickets", params={"estado": "resuelto"})) == [t2]
    assert ids(sesion.get("/api/tickets", params={"estado": "nuevo"})) == [t3]
    assert ids(sesion.get("/api/tickets", params={"estado": "cerrado"})) == []


def test_filtro_por_categoria(sesion, agente, otro_agente):
    t1, t2, t3 = preparar(sesion, agente, otro_agente)
    assert ids(sesion.get("/api/tickets", params={"categoria": "facturacion"})) == [t3, t1]
    assert ids(sesion.get("/api/tickets", params={"categoria": "cuenta"})) == [t2]
    assert ids(sesion.get("/api/tickets", params={"categoria": "tecnico"})) == []


def test_filtro_por_prioridad(sesion, agente, otro_agente):
    t1, t2, t3 = preparar(sesion, agente, otro_agente)
    assert ids(sesion.get("/api/tickets", params={"prioridad": "alta"})) == [t1]
    assert ids(sesion.get("/api/tickets", params={"prioridad": "urgente"})) == [t2]
    assert ids(sesion.get("/api/tickets", params={"prioridad": "media"})) == [t3]
    assert ids(sesion.get("/api/tickets", params={"prioridad": "baja"})) == []


def test_filtro_por_asignado_a(sesion, agente, otro_agente):
    t1, t2, _ = preparar(sesion, agente, otro_agente)
    assert ids(sesion.get("/api/tickets", params={"asignado_a": agente.id})) == [t1]
    assert ids(sesion.get("/api/tickets", params={"asignado_a": otro_agente.id})) == [t2]
    assert ids(sesion.get("/api/tickets", params={"asignado_a": 9999})) == []


def test_filtro_q_busca_en_asunto_y_texto(sesion, agente, otro_agente):
    t1, t2, t3 = preparar(sesion, agente, otro_agente)
    assert ids(sesion.get("/api/tickets", params={"q": "factura"})) == [t3, t1]
    assert ids(sesion.get("/api/tickets", params={"q": "login"})) == [t2]
    assert ids(sesion.get("/api/tickets", params={"q": "contraseña"})) == [t2]
    assert ids(sesion.get("/api/tickets", params={"q": "FACTURA"})) == [t3, t1]
    assert ids(sesion.get("/api/tickets", params={"q": "inexistente"})) == []


def test_filtro_q_vacio_no_filtra(sesion, agente, otro_agente):
    preparar(sesion, agente, otro_agente)
    assert sesion.get("/api/tickets", params={"q": "  "}).json()["total"] == 3


def test_filtro_q_trata_comodines_como_texto(sesion):
    t = nuevo(sesion, asunto="Descuento del 50%", texto="a_b")
    nuevo(sesion, asunto="Otro", texto="ab")
    assert ids(sesion.get("/api/tickets", params={"q": "50%"})) == [t["id"]]
    assert ids(sesion.get("/api/tickets", params={"q": "a_b"})) == [t["id"]]
    assert sesion.get("/api/tickets", params={"q": "%"}).json()["total"] == 1


def test_filtros_combinados(sesion, agente, otro_agente):
    t1, _, t3 = preparar(sesion, agente, otro_agente)
    r = sesion.get("/api/tickets", params={"categoria": "facturacion", "estado": "en_curso"})
    assert ids(r) == [t1]
    r = sesion.get("/api/tickets", params={"categoria": "facturacion", "q": "pedido"})
    assert ids(r) == [t3]
    r = sesion.get("/api/tickets", params={"estado": "resuelto", "asignado_a": agente.id})
    assert ids(r) == []


def test_filtros_con_paginacion_cuentan_solo_los_filtrados(sesion, agente, otro_agente):
    preparar(sesion, agente, otro_agente)
    d = sesion.get(
        "/api/tickets", params={"categoria": "facturacion", "page": 1, "page_size": 1}
    ).json()
    assert (d["total"], d["paginas"], len(d["items"])) == (2, 2, 1)


@pytest.mark.parametrize(
    "params",
    [
        {"estado": "inventado"},
        {"prioridad": "critica"},
        {"categoria": "magia"},
        {"asignado_a": "x"},
        {"asignado_a": 0},
    ],
)
def test_filtros_invalidos_dan_422(sesion, params):
    assert sesion.get("/api/tickets", params=params).status_code == 422


# --- PATCH ---


def test_patch_cambia_todos_los_campos(sesion, agente, reloj):
    t = nuevo(sesion)
    reloj.avanzar(hours=1)
    r = sesion.patch(
        f"/api/tickets/{t['id']}",
        json={"estado": "en_curso", "prioridad": "urgente", "categoria": "tecnico",
              "asignado_a": agente.id},
    )  # fmt: skip
    assert r.status_code == 200
    d = r.json()
    assert (d["estado"], d["prioridad"], d["categoria"], d["asignado_a"]) == (
        "en_curso",
        "urgente",
        "tecnico",
        agente.id,
    )
    assert d["actualizado_en"] == "2026-03-02T10:00:00Z"
    assert d["creado_en"] == "2026-03-02T09:00:00Z"
    assert sesion.get(f"/api/tickets/{t['id']}").json() == d


def test_patch_parcial_solo_toca_lo_enviado(sesion, agente):
    t = nuevo(sesion)
    sesion.patch(f"/api/tickets/{t['id']}", json={"prioridad": "alta", "asignado_a": agente.id})
    d = sesion.patch(f"/api/tickets/{t['id']}", json={"estado": "esperando_cliente"}).json()
    assert (d["estado"], d["prioridad"], d["asignado_a"]) == (
        "esperando_cliente",
        "alta",
        agente.id,
    )
    assert d["asunto"] == t["asunto"] and d["texto"] == t["texto"]


def test_patch_null_desasigna_y_quita_categoria(sesion, agente):
    t = nuevo(sesion)
    sesion.patch(f"/api/tickets/{t['id']}", json={"categoria": "otro", "asignado_a": agente.id})
    d = sesion.patch(f"/api/tickets/{t['id']}", json={"categoria": None, "asignado_a": None}).json()
    assert (d["categoria"], d["asignado_a"]) == (None, None)


def test_patch_resuelve_y_reabre(sesion, reloj):
    t = nuevo(sesion)
    reloj.avanzar(hours=2)
    d = sesion.patch(f"/api/tickets/{t['id']}", json={"estado": "resuelto"}).json()
    assert d["resuelto_en"] == "2026-03-02T11:00:00Z"
    reloj.avanzar(hours=1)
    d = sesion.patch(f"/api/tickets/{t['id']}", json={"estado": "cerrado"}).json()
    assert d["resuelto_en"] == "2026-03-02T11:00:00Z"
    d = sesion.patch(f"/api/tickets/{t['id']}", json={"estado": "en_curso"}).json()
    assert d["resuelto_en"] is None


def test_patch_inexistente_da_404(sesion):
    assert sesion.patch("/api/tickets/999", json={"estado": "cerrado"}).status_code == 404


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"estado": "inventado"},
        {"prioridad": "critica"},
        {"categoria": "magia"},
        {"asignado_a": "x"},
        {"asignado_a": 0},
        {"asignado_a": 9999},
        {"estado": None},
        {"prioridad": None},
        {},
        {"asunto": "no editable"},
    ],
)
def test_patch_con_valores_invalidos_da_422_y_no_cambia_nada(sesion, cuerpo):
    t = nuevo(sesion)
    assert sesion.patch(f"/api/tickets/{t['id']}", json=cuerpo).status_code == 422
    assert sesion.get(f"/api/tickets/{t['id']}").json() == t


def test_patch_no_asigna_a_usuarios_desactivados(sesion, otro_agente, db):
    db.execute("UPDATE usuarios SET activo = 0 WHERE id = ?", (otro_agente.id,))
    db.commit()
    t = nuevo(sesion)
    r = sesion.patch(f"/api/tickets/{t['id']}", json={"asignado_a": otro_agente.id})
    assert r.status_code == 422


# --- documentación ---


def test_los_modelos_aparecen_en_openapi_y_docs(sesion):
    assert sesion.get("/docs").status_code == 200
    spec = sesion.get("/openapi.json").json()
    for modelo in ("TicketCrear", "TicketActualizar", "TicketSalida", "PaginaTickets"):
        assert modelo in spec["components"]["schemas"]
    assert set(spec["paths"]["/api/tickets"]) == {"get", "post"}
    assert set(spec["paths"]["/api/tickets/{ticket_id}"]) == {"get", "patch"}
    assert "201" in spec["paths"]["/api/tickets"]["post"]["responses"]
