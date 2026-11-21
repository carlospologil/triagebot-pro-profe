import sqlite3

import pytest

from app import cli
from app.auth import verify_password


@pytest.fixture
def entorno(settings, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", settings.secret_key)
    monkeypatch.setenv("DATABASE_PATH", settings.database_path)
    return settings


def _contrasenas(monkeypatch, *valores):
    respuestas = iter(valores)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(respuestas))


def _filas(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM usuarios").fetchall()
    finally:
        conn.close()


def test_crear_admin(entorno, monkeypatch, capsys):
    _contrasenas(monkeypatch, "una-clave-segura", "una-clave-segura")
    codigo = cli.main(["crear-admin", "--email", "Admin@Example.com", "--nombre", "Admin"])
    assert codigo == 0
    salida = capsys.readouterr()
    assert "admin@example.com" in salida.out
    assert "una-clave-segura" not in salida.out + salida.err
    (fila,) = _filas(entorno.database_path)
    assert fila["rol"] == "admin"
    assert verify_password("una-clave-segura", fila["password_hash"])


def test_crear_admin_contrasena_corta(entorno, monkeypatch, capsys):
    _contrasenas(monkeypatch, "corta", "corta")
    codigo = cli.main(["crear-admin", "--email", "a@example.com", "--nombre", "A"])
    assert codigo == 1
    assert "al menos 10 caracteres" in capsys.readouterr().err
    assert _filas(entorno.database_path) == []


def test_crear_admin_contrasenas_distintas(entorno, monkeypatch, capsys):
    _contrasenas(monkeypatch, "una-clave-segura", "otra-clave-segura")
    assert cli.main(["crear-admin", "--email", "a@example.com", "--nombre", "A"]) == 1
    assert "no coinciden" in capsys.readouterr().err


def test_crear_admin_email_duplicado(entorno, monkeypatch, capsys):
    _contrasenas(monkeypatch, "una-clave-segura", "una-clave-segura")
    cli.main(["crear-admin", "--email", "a@example.com", "--nombre", "A"])
    _contrasenas(monkeypatch, "una-clave-segura", "una-clave-segura")
    assert cli.main(["crear-admin", "--email", "A@example.com", "--nombre", "B"]) == 1
    assert "Ya existe" in capsys.readouterr().err
