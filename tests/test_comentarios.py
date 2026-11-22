import pytest

from app.services import comentarios
from app.services.usuarios import create_user

PASSWORD = "una-clave-segura"
HX = {"HX-Request": "true"}


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
def ticket_id(db):
    cursor = db.execute(
        "INSERT INTO tickets (asunto, descripcion, solicitante_nombre, solicitante_email, "
        "creado_en, actualizado_en) VALUES ('No puedo entrar', 'Texto', 'Marta', "
        "'marta@example.com', '2026-03-02T06:30:00Z', '2026-03-02T06:30:00Z')"
    )
    db.commit()
    return cursor.lastrowid


def filas(db):
    return db.execute("SELECT * FROM comentarios ORDER BY id").fetchall()


# --- alta ---


def test_alta_con_htmx_guarda_autor_y_fecha_y_responde_con_la_linea_de_tiempo(
    sesion, db, ticket_id, agente
):
    r = sesion.post(
        f"/tickets/{ticket_id}/comentarios", data={"cuerpo": "Llamar al cliente"}, headers=HX
    )
    assert r.status_code == 200
    guardados = filas(db)
    assert len(guardados) == 1
    assert guardados[0]["ticket_id"] == ticket_id
    assert guardados[0]["autor_id"] == agente.id
    assert guardados[0]["cuerpo"] == "Llamar al cliente"
    assert guardados[0]["interno"] == 1
    assert guardados[0]["creado_en"] == "2026-03-02T09:00:00Z"
    assert 'id="panel-comentarios"' in r.text
    assert 'id="historial"' in r.text
    assert 'hx-swap-oob="true"' in r.text
    assert "Llamar al cliente" in r.text
    assert "Ana · 02/03/2026 09:00 UTC" in r.text
    assert "alert" not in r.text


def test_alta_sin_htmx_redirige_al_detalle(sesion, db, ticket_id):
    r = sesion.post(
        f"/tickets/{ticket_id}/comentarios", data={"cuerpo": "Nota"}, follow_redirects=False
    )
    assert (r.status_code, r.headers["location"]) == (303, f"/tickets/{ticket_id}")
    assert len(filas(db)) == 1


def test_el_formulario_usa_htmx(sesion, ticket_id):
    texto = sesion.get(f"/tickets/{ticket_id}").text
    assert 'hx-target="#panel-comentarios"' in texto
    assert f'hx-post="/tickets/{ticket_id}/comentarios"' in texto


def test_alta_en_ticket_inexistente_da_404(sesion, db):
    r = sesion.post("/tickets/999/comentarios", data={"cuerpo": "Nota"}, headers=HX)
    assert r.status_code == 404
    assert filas(db) == []


def test_alta_sin_sesion_redirige_al_login(client, db, ticket_id):
    r = client.post(
        f"/tickets/{ticket_id}/comentarios", data={"cuerpo": "Nota"}, follow_redirects=False
    )
    assert (r.status_code, r.headers["location"]) == (303, "/login")
    assert filas(db) == []


def test_el_comentario_conserva_los_saltos_de_linea_normalizados(sesion, db, ticket_id):
    sesion.post(f"/tickets/{ticket_id}/comentarios", data={"cuerpo": "  uno\r\ndos  "}, headers=HX)
    assert filas(db)[0]["cuerpo"] == "uno\ndos"


# --- validación ---


@pytest.mark.parametrize("cuerpo", ["", "   ", "\r\n\t \n"])
def test_comentario_vacio_se_rechaza_con_mensaje_junto_al_campo(sesion, db, ticket_id, cuerpo):
    r = sesion.post(f"/tickets/{ticket_id}/comentarios", data={"cuerpo": cuerpo}, headers=HX)
    assert r.status_code == 422
    assert "Escribe un comentario antes de enviarlo." in r.text
    assert 'aria-describedby="error-cuerpo"' in r.text
    assert 'id="error-cuerpo"' in r.text
    assert filas(db) == []


def test_comentario_sin_campo_se_rechaza(sesion, db, ticket_id):
    r = sesion.post(f"/tickets/{ticket_id}/comentarios", data={}, headers=HX)
    assert r.status_code == 422
    assert filas(db) == []


def test_comentario_de_mas_de_5000_caracteres_se_rechaza_y_conserva_el_texto(sesion, db, ticket_id):
    largo = "a" * 5001
    r = sesion.post(f"/tickets/{ticket_id}/comentarios", data={"cuerpo": largo}, headers=HX)
    assert r.status_code == 422
    assert "no puede superar los 5000 caracteres" in r.text
    assert 'id="error-cuerpo"' in r.text
    assert largo in r.text
    assert filas(db) == []


def test_comentario_de_exactamente_5000_caracteres_se_acepta(sesion, db, ticket_id):
    r = sesion.post(f"/tickets/{ticket_id}/comentarios", data={"cuerpo": "a" * 5000}, headers=HX)
    assert r.status_code == 200
    assert len(filas(db)[0]["cuerpo"]) == 5000


def test_el_limite_cuenta_los_saltos_de_linea_crlf_como_un_caracter(sesion, db, ticket_id):
    cuerpo = "\r\n".join(["a" * 49] * 100)  # 4900 caracteres + 99 saltos = 4999
    r = sesion.post(f"/tickets/{ticket_id}/comentarios", data={"cuerpo": cuerpo}, headers=HX)
    assert r.status_code == 200


def test_error_sin_htmx_repinta_la_pagina_con_el_mensaje(sesion, db, ticket_id):
    r = sesion.post(f"/tickets/{ticket_id}/comentarios", data={"cuerpo": " "})
    assert r.status_code == 422
    assert "<html" in r.text
    assert "Escribe un comentario antes de enviarlo." in r.text
    assert filas(db) == []


def test_validar_en_el_servicio():
    assert comentarios.validar("  hola \n") == "hola"
    with pytest.raises(comentarios.ComentarioInvalidoError):
        comentarios.validar(" ")
    with pytest.raises(comentarios.ComentarioInvalidoError):
        comentarios.validar("a" * 5001)


# --- escapado ---


def test_el_contenido_del_comentario_se_escapa(sesion, ticket_id):
    carga = '<script>alert("x")</script><img src=x onerror=alert(1)> & <b>negrita</b>'
    r = sesion.post(f"/tickets/{ticket_id}/comentarios", data={"cuerpo": carga}, headers=HX)
    assert r.status_code == 200
    for texto in (r.text, sesion.get(f"/tickets/{ticket_id}").text):
        assert "<script>alert" not in texto
        assert "<img src=x" not in texto
        assert "<b>negrita</b>" not in texto
        assert "&lt;script&gt;alert(&#34;x&#34;)&lt;/script&gt;" in texto
        assert "&lt;img src=x onerror=alert(1)&gt; &amp; &lt;b&gt;negrita&lt;/b&gt;" in texto


def test_el_borrador_con_error_tambien_se_escapa(sesion, ticket_id):
    carga = "<script>alert(1)</script>" + "a" * 5001
    r = sesion.post(f"/tickets/{ticket_id}/comentarios", data={"cuerpo": carga}, headers=HX)
    assert r.status_code == 422
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r.text


# --- línea de tiempo ---


def test_la_linea_de_tiempo_mezcla_comentarios_y_cambios_en_orden(sesion, db, reloj, ticket_id):
    post = sesion.post
    reloj.avanzar(minutes=1)
    post(f"/tickets/{ticket_id}/comentarios", data={"cuerpo": "Primer comentario"}, headers=HX)
    reloj.avanzar(minutes=1)
    post(f"/tickets/{ticket_id}/estado", data={"estado": "en_curso"}, headers=HX)
    reloj.avanzar(minutes=1)
    post(f"/tickets/{ticket_id}/comentarios", data={"cuerpo": "Segundo comentario"}, headers=HX)

    texto = sesion.get(f"/tickets/{ticket_id}").text
    posiciones = [
        texto.index("Primer comentario"),
        texto.index("Cambio de estado"),
        texto.index("Segundo comentario"),
    ]
    assert posiciones == sorted(posiciones)
    assert "02/03/2026 09:01 UTC" in texto
    assert "02/03/2026 09:03 UTC" in texto


def test_linea_de_tiempo_del_servicio_ordena_por_fecha_aunque_se_insertara_antes(
    db, agente, ticket_id
):
    db.execute(
        "INSERT INTO comentarios (ticket_id, autor_id, cuerpo, creado_en) "
        "VALUES (?, ?, 'tarde', '2026-03-02T12:00:00Z')",
        (ticket_id, agente.id),
    )
    db.execute(
        "INSERT INTO auditoria (ticket_id, accion, creado_en) "
        "VALUES (?, 'estado_cambiado', '2026-03-02T10:00:00Z')",
        (ticket_id,),
    )
    db.execute(
        "INSERT INTO comentarios (ticket_id, autor_id, cuerpo, creado_en) "
        "VALUES (?, ?, 'pronto', '2026-03-02T08:00:00Z')",
        (ticket_id, agente.id),
    )
    db.commit()
    entradas = comentarios.linea_de_tiempo(db, ticket_id)
    assert [e.tipo for e in entradas] == ["comentario", "evento", "comentario"]
    assert [e.creado_en for e in entradas] == sorted(e.creado_en for e in entradas)


def test_los_comentarios_de_otro_ticket_no_aparecen(sesion, db, ticket_id):
    otro = db.execute(
        "INSERT INTO tickets (asunto, descripcion, solicitante_nombre, solicitante_email, "
        "creado_en, actualizado_en) VALUES ('Otro', 'x', 'N', 'n@example.com', "
        "'2026-03-02T06:30:00Z', '2026-03-02T06:30:00Z')"
    ).lastrowid
    db.commit()
    sesion.post(f"/tickets/{otro}/comentarios", data={"cuerpo": "Solo del otro"}, headers=HX)
    assert "Solo del otro" not in sesion.get(f"/tickets/{ticket_id}").text


def test_comentario_de_autor_eliminado_se_muestra_con_texto_neutro(sesion, db, ticket_id):
    db.execute(
        "INSERT INTO comentarios (ticket_id, autor_id, cuerpo, creado_en) "
        "VALUES (?, NULL, 'huérfano', '2026-03-02T08:00:00Z')",
        (ticket_id,),
    )
    db.commit()
    assert "Usuario eliminado" in sesion.get(f"/tickets/{ticket_id}").text
