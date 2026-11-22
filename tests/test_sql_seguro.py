import ast
from pathlib import Path

import pytest

from app.services import tickets as servicio
from app.services.auditoria import listar as listar_auditoria
from app.services.usuarios import create_user

APP = Path(__file__).resolve().parent.parent / "app"
PASSWORD = "una-clave-segura"
METODOS_SQL = {"execute", "executemany", "executescript"}
# Fragmentos que construye el propio código (nombres de columna fijos, marcadores `?`).
FRAGMENTOS_PERMITIDOS = {"where", "asignaciones", "marcas", "desde", "columna"}
INYECCIONES = [
    "'; DROP TABLE tickets; --",
    "' OR '1'='1",
    '" OR 1=1 --',
    "%' ; DELETE FROM usuarios; --",
    "1; DROP TABLE usuarios",
]


def _llamadas_sql():
    for ruta in sorted(APP.rglob("*.py")):
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if (
                isinstance(nodo, ast.Call)
                and isinstance(nodo.func, ast.Attribute)
                and nodo.func.attr in METODOS_SQL
                and nodo.args
            ):
                yield ruta.relative_to(APP), nodo


def _es_literal(nodo: ast.expr) -> bool:
    return isinstance(nodo, ast.Constant) and isinstance(nodo.value, str)


def _es_seguro(nodo: ast.expr) -> bool:
    """Literal, o f-string que solo interpola fragmentos fijos conocidos (nunca texto de usuario);
    nada de `+`, `%` ni `.format`."""
    if _es_literal(nodo):
        return True
    if isinstance(nodo, ast.JoinedStr):
        return all(
            _es_literal(parte)
            or (
                isinstance(parte, ast.FormattedValue)
                and isinstance(parte.value, ast.Name)
                and parte.value.id in FRAGMENTOS_PERMITIDOS
            )
            for parte in nodo.values
        )
    return False


def test_hay_llamadas_sql_que_revisar():
    assert len(list(_llamadas_sql())) > 20


def test_ninguna_consulta_se_construye_concatenando_texto():
    sospechosas = []
    for ruta, nodo in _llamadas_sql():
        sentencia = nodo.args[0]
        # `conn.execute(statement)` recorre las migraciones constantes de db.py.
        if isinstance(sentencia, ast.Name) and (ruta.name, sentencia.id) == ("db.py", "statement"):
            continue
        if not _es_seguro(sentencia):
            sospechosas.append(f"{ruta}:{nodo.lineno}")
    assert not sospechosas, f"SQL construido dinámicamente: {sospechosas}"


def test_los_nombres_de_columna_dinamicos_estan_en_lista_cerrada():
    with pytest.raises(ValueError):
        servicio._clausula_set({"estado = 'cerrado', asignado_a": 1})
    from app.services.metricas import _contar_por

    with pytest.raises(ValueError):
        _contar_por(None, "estado; DROP TABLE tickets", {})


@pytest.fixture
def agente(db):
    return create_user(db, email="ana@example.com", nombre="Ana", password=PASSWORD)


def _tablas(db):
    return {f[0] for f in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


@pytest.mark.parametrize("carga", INYECCIONES)
def test_los_filtros_de_la_bandeja_y_la_api_tratan_la_entrada_como_dato(client, db, agente, carga):
    client.post("/login", data={"email": agente.email, "password": PASSWORD})
    tablas = _tablas(db)
    cuentas = db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
    for ruta in ("/bandeja", "/api/tickets", "/api/tickets/export.csv", "/admin/auditoria"):
        for parametro in ("q", "estado", "categoria", "usuario", "accion"):
            r = client.get(ruta, params={parametro: carga})
            assert r.status_code < 500, (ruta, parametro)
    assert _tablas(db) == tablas
    assert db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == cuentas


@pytest.mark.parametrize("carga", INYECCIONES)
def test_un_ticket_con_texto_malicioso_se_guarda_y_se_busca_literalmente(client, db, agente, carga):
    client.post("/login", data={"email": agente.email, "password": PASSWORD})
    r = client.post(
        "/api/tickets",
        json={
            "asunto": carga,
            "texto": carga,
            "email_cliente": "c@example.com",
            "nombre_cliente": carga,
        },
    )
    assert r.status_code == 201
    assert r.json()["asunto"] == carga
    assert "tickets" in _tablas(db)
    pagina = client.get("/api/tickets", params={"q": carga}).json()
    assert pagina["total"] == 1


@pytest.mark.parametrize("carga", INYECCIONES)
def test_el_login_con_texto_malicioso_no_se_salta_la_autenticacion(client, db, agente, carga):
    r = client.post(
        "/login", data={"email": carga, "password": carga}, follow_redirects=False
    )
    assert r.status_code == 401
    datos = {"email": f"{agente.email}{carga}", "password": carga}
    r = client.post("/login", data=datos, follow_redirects=False)
    assert r.status_code == 401


def test_el_filtro_de_auditoria_por_usuario_malicioso_no_falla(db):
    pagina = listar_auditoria(db, usuario="x' OR '1'='1", accion="a'; DROP TABLE auditoria; --")
    assert pagina.total == 0
    assert "auditoria" in _tablas(db)
