import sqlite3

import pytest

from app import cli
from app.services import demo
from app.services.usuarios import UsuarioError


@pytest.fixture
def entorno(settings, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", settings.secret_key)
    monkeypatch.setenv("DATABASE_PATH", settings.database_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return settings


def _consulta(path, sql):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_demo_crea_usuarios_y_tickets(entorno, capsys):
    assert cli.main(["demo"]) == 0
    filas = _consulta(entorno.database_path, "SELECT rol, COUNT(*) FROM usuarios GROUP BY rol")
    roles = dict(filas)
    assert roles == {"admin": 1, "agente": 3}
    (total,) = _consulta(entorno.database_path, "SELECT COUNT(*) FROM tickets")[0]
    assert total == 60 == demo.TOTAL_TICKETS


def test_demo_imprime_las_credenciales(entorno, capsys):
    cli.main(["demo"])
    salida = capsys.readouterr().out
    for email, _, _, password in demo.USUARIOS_DEMO:
        assert email in salida
        assert password in salida


def test_demo_tickets_variados(entorno):
    cli.main(["demo"])
    ruta = entorno.database_path
    estados = {f[0] for f in _consulta(ruta, "SELECT DISTINCT estado FROM tickets")}
    prioridades = {f[0] for f in _consulta(ruta, "SELECT DISTINCT prioridad FROM tickets")}
    categorias = {f[0] for f in _consulta(ruta, "SELECT DISTINCT categoria FROM tickets")}
    fechas = {f[0][:10] for f in _consulta(ruta, "SELECT creado_en FROM tickets")}
    assert len(estados) >= 4
    assert len(prioridades) >= 3
    assert len(categorias) >= 5
    assert len(fechas) >= 10


def test_demo_no_llama_al_llm(entorno, monkeypatch):
    def prohibido(*args, **kwargs):
        raise AssertionError("El comando demo no debe crear un cliente LLM")

    monkeypatch.setattr(cli, "crear_cliente", prohibido)
    monkeypatch.setenv("OPENROUTER_API_KEY", "clave-que-no-debe-usarse")
    assert cli.main(["demo"]) == 0


def test_demo_dos_veces_falla_sin_duplicar(entorno, capsys):
    assert cli.main(["demo"]) == 0
    capsys.readouterr()
    assert cli.main(["demo"]) == 1
    assert "Ya existen" in capsys.readouterr().err
    assert _consulta(entorno.database_path, "SELECT COUNT(*) FROM tickets")[0][0] == 60


def test_crear_datos_demo_devuelve_las_credenciales(db, reloj):
    credenciales = demo.crear_datos_demo(db, reloj)
    assert credenciales == [(e, r, p) for e, _, r, p in demo.USUARIOS_DEMO]


def test_crear_datos_demo_lanza_si_ya_existen(db, reloj):
    demo.crear_datos_demo(db, reloj)
    with pytest.raises(UsuarioError):
        demo.crear_datos_demo(db, reloj)


def test_los_usuarios_demo_pueden_iniciar_sesion(client, db, reloj):
    demo.crear_datos_demo(db, reloj)
    for email, _, _, password in demo.USUARIOS_DEMO:
        r = client.post(
            "/login", data={"email": email, "password": password}, follow_redirects=False
        )
        assert r.status_code == 303, email
        assert client.get("/bandeja").status_code == 200
        client.post("/logout")


def test_los_tickets_demo_aparecen_en_la_bandeja_y_el_panel(client, db, reloj):
    demo.crear_datos_demo(db, reloj)
    email, _, _, password = demo.USUARIOS_DEMO[0]
    client.post("/login", data={"email": email, "password": password})
    assert "Cobro duplicado" in client.get("/bandeja").text
    assert client.get("/panel").status_code == 200
