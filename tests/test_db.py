import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import MIGRATIONS, Migration, connect, current_version, init_db, migrate
from app.main import create_app

TABLAS = {"usuarios", "tickets", "comentarios", "auditoria", "schema_version"}
AHORA = "2026-01-01T00:00:00Z"


def nombres(conn, tipo):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = ?", (tipo,))
    return {r["name"] for r in rows if not r["name"].startswith("sqlite_")}


def insertar_usuario(conn, email="a@example.com"):
    return conn.execute(
        "INSERT INTO usuarios (email, nombre, password_hash, creado_en) VALUES (?, 'A', 'x', ?)",
        (email, AHORA),
    ).lastrowid


def insertar_ticket(conn, asignado_a=None):
    return conn.execute(
        "INSERT INTO tickets (asunto, descripcion, solicitante_nombre, solicitante_email,"
        " asignado_a, creado_en, actualizado_en) VALUES ('s', 'd', 'n', 'n@example.com', ?, ?, ?)",
        (asignado_a, AHORA, AHORA),
    ).lastrowid


# --- conexión ---


def test_connect_activa_foreign_keys_y_row_factory(tmp_path):
    conn = connect(str(tmp_path / "x.db"))
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.row_factory is sqlite3.Row
    assert conn.execute("SELECT 1 AS uno").fetchone()["uno"] == 1
    conn.close()


# --- migraciones ---


def test_migracion_inicial_crea_tablas_y_registra_version(db):
    assert TABLAS <= nombres(db, "table")
    assert current_version(db) == MIGRATIONS[-1].version
    row = db.execute("SELECT version, nombre FROM schema_version").fetchone()
    assert (row["version"], row["nombre"]) == (1, "esquema_inicial")


def test_migrate_es_idempotente(db):
    antes_tablas = nombres(db, "table")
    antes_indices = nombres(db, "index")
    insertar_usuario(db)
    db.commit()

    assert migrate(db) == []
    assert migrate(db) == []

    assert nombres(db, "table") == antes_tablas
    assert nombres(db, "index") == antes_indices
    assert db.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == len(MIGRATIONS)
    assert db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 1


def test_migraciones_se_aplican_en_orden_y_solo_las_pendientes(settings):
    conn = connect(settings.database_path)
    uno = Migration(1, "uno", ("CREATE TABLE a (id INTEGER)",))
    dos = Migration(2, "dos", ("CREATE TABLE b (id INTEGER)",))
    assert migrate(conn, (uno,)) == [1]
    assert migrate(conn, (uno, dos)) == [2]
    assert migrate(conn, (uno, dos)) == []
    versiones = [r["version"] for r in conn.execute("SELECT version FROM schema_version")]
    assert versiones == [1, 2]
    conn.close()


def test_migracion_fallida_hace_rollback(settings):
    conn = connect(settings.database_path)
    mala = Migration(1, "mala", ("CREATE TABLE a (id INTEGER)", "SENTENCIA INVALIDA"))
    with pytest.raises(sqlite3.OperationalError):
        migrate(conn, (mala,))
    assert "a" not in nombres(conn, "table")
    assert current_version(conn) == 0
    conn.close()


def test_versiones_duplicadas_o_desordenadas_se_rechazan(db):
    m = Migration(5, "x", ())
    with pytest.raises(ValueError):
        migrate(db, (m, m))
    with pytest.raises(ValueError):
        migrate(db, (Migration(7, "x", ()), Migration(6, "y", ())))


def test_init_db_dos_veces_no_falla_ni_duplica(settings):
    assert init_db(settings.database_path) == [m.version for m in MIGRATIONS]
    assert init_db(settings.database_path) == []
    conn = connect(settings.database_path)
    assert current_version(conn) == MIGRATIONS[-1].version
    assert TABLAS <= nombres(conn, "table")
    conn.close()


def test_arrancar_la_app_dos_veces_no_duplica_ni_falla(settings):
    for _ in range(2):
        with TestClient(create_app(settings)) as c:
            assert c.get("/health").status_code == 200
    conn = connect(settings.database_path)
    assert conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == len(MIGRATIONS)
    conn.close()


def test_arrancar_la_app_aplica_migraciones(client, settings):
    conn = connect(settings.database_path)
    assert TABLAS <= nombres(conn, "table")
    conn.close()


def test_cada_test_usa_una_base_de_datos_distinta(db, settings, tmp_path):
    assert settings.database_path.startswith(str(tmp_path))
    assert db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0
    insertar_usuario(db)
    db.commit()


def test_la_base_de_datos_anterior_no_se_comparte(db):
    assert db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0


def test_dos_settings_de_tests_apuntan_a_ficheros_distintos(tmp_path_factory):
    a = Settings(secret_key="k", database_path=str(tmp_path_factory.mktemp("a") / "t.db"))
    b = Settings(secret_key="k", database_path=str(tmp_path_factory.mktemp("b") / "t.db"))
    assert a.database_path != b.database_path


# --- índices ---


@pytest.mark.parametrize(
    ("tabla", "columna"),
    [
        ("tickets", "estado"),
        ("tickets", "prioridad"),
        ("tickets", "categoria"),
        ("tickets", "asignado_a"),
        ("tickets", "fecha_limite"),
        ("tickets", "creado_en"),
        ("comentarios", "ticket_id"),
        ("comentarios", "autor_id"),
        ("auditoria", "ticket_id"),
        ("auditoria", "usuario_id"),
        ("auditoria", "creado_en"),
    ],
)
def test_existe_indice_en_columnas_de_filtrado(db, tabla, columna):
    indices = db.execute(f"PRAGMA index_list({tabla})").fetchall()
    columnas = {db.execute(f"PRAGMA index_info({i['name']})").fetchone()["name"] for i in indices}
    assert columna in columnas


# --- claves foráneas ---


def test_fk_ticket_con_usuario_inexistente_falla(db):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        insertar_ticket(db, asignado_a=999)


def test_fk_comentario_con_ticket_inexistente_falla(db):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        db.execute(
            "INSERT INTO comentarios (ticket_id, cuerpo, creado_en) VALUES (999, 'c', ?)",
            (AHORA,),
        )


def test_fk_comentario_con_autor_inexistente_falla(db):
    ticket = insertar_ticket(db)
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        db.execute(
            "INSERT INTO comentarios (ticket_id, autor_id, cuerpo, creado_en) "
            "VALUES (?, 999, 'c', ?)",
            (ticket, AHORA),
        )


def test_fk_auditoria_con_referencias_inexistentes_falla(db):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        db.execute(
            "INSERT INTO auditoria (ticket_id, accion, creado_en) VALUES (999, 'a', ?)",
            (AHORA,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        db.execute(
            "INSERT INTO auditoria (usuario_id, accion, creado_en) VALUES (999, 'a', ?)",
            (AHORA,),
        )


def test_borrar_ticket_borra_comentarios_y_conserva_auditoria(db):
    ticket = insertar_ticket(db)
    db.execute(
        "INSERT INTO comentarios (ticket_id, cuerpo, creado_en) VALUES (?, 'c', ?)",
        (ticket, AHORA),
    )
    db.execute(
        "INSERT INTO auditoria (ticket_id, accion, creado_en) VALUES (?, 'creado', ?)",
        (ticket, AHORA),
    )
    db.execute("DELETE FROM tickets WHERE id = ?", (ticket,))
    assert db.execute("SELECT COUNT(*) FROM comentarios").fetchone()[0] == 0
    fila = db.execute("SELECT ticket_id FROM auditoria").fetchone()
    assert fila["ticket_id"] is None


def test_borrar_usuario_desasigna_tickets(db):
    usuario = insertar_usuario(db)
    ticket = insertar_ticket(db, asignado_a=usuario)
    db.execute("DELETE FROM usuarios WHERE id = ?", (usuario,))
    fila = db.execute("SELECT asignado_a FROM tickets WHERE id = ?", (ticket,)).fetchone()
    assert fila["asignado_a"] is None


def test_email_de_usuario_es_unico(db):
    insertar_usuario(db, "dup@example.com")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        insertar_usuario(db, "dup@example.com")


def test_conexion_por_peticion_se_puede_usar_desde_otro_hilo(settings):
    import threading

    init_db(settings.database_path)
    conn = connect(settings.database_path)
    resultado = []
    hilo = threading.Thread(target=lambda: resultado.append(conn.execute("SELECT 1").fetchone()[0]))
    hilo.start()
    hilo.join()
    conn.close()
    assert resultado == [1]
