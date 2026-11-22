import sqlite3
from pathlib import Path

import pytest

from app import cli
from app.auth import verify_password
from tests.conftest import FalsoLLM

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def entorno(settings, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", settings.secret_key)
    monkeypatch.setenv("DATABASE_PATH", settings.database_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return settings


def _contrasenas(monkeypatch, *valores):
    respuestas = iter(valores)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(respuestas))


def _filas(path, tabla="usuarios"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(f"SELECT * FROM {tabla} ORDER BY id").fetchall()
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


@pytest.fixture
def llm_cli(monkeypatch):
    """Sustituye la creación del cliente de OpenRouter por un falso: sin red."""
    falso = FalsoLLM()
    monkeypatch.setenv("OPENROUTER_API_KEY", "clave-falsa")
    monkeypatch.setattr(cli, "crear_cliente", lambda api_key: falso)
    return falso


def test_importar_csv_clasifica_e_informa(entorno, llm_cli, capsys):
    codigo = cli.main(["importar", str(FIXTURES / "tickets.csv")])
    assert codigo == 0
    salida = capsys.readouterr()
    assert "Importados: 4. Saltados: 2." in salida.out
    assert "Fila 3: sin texto" in salida.err
    assert len(llm_cli.llamadas) == 4
    filas = _filas(entorno.database_path, "tickets")
    assert len(filas) == 4
    assert {f["categoria"] for f in filas} == {"otro"}


def test_importar_json(entorno, llm_cli, capsys):
    assert cli.main(["importar", str(FIXTURES / "tickets.json")]) == 0
    assert "Importados: 2. Saltados: 3." in capsys.readouterr().out
    assert len(_filas(entorno.database_path, "tickets")) == 2


def test_importar_sin_clasificar_no_llama_al_llm(entorno, monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", "clave-falsa")

    def no_debe_crearse(api_key):
        raise AssertionError("no debe crearse el cliente LLM")

    monkeypatch.setattr(cli, "crear_cliente", no_debe_crearse)
    codigo = cli.main(["importar", str(FIXTURES / "tickets.csv"), "--sin-clasificar"])
    assert codigo == 0
    assert "Importados: 4. Saltados: 2." in capsys.readouterr().out
    filas = _filas(entorno.database_path, "tickets")
    assert {f["categoria"] for f in filas} == {"sin_clasificar"}


def test_importar_sin_clave_avisa_y_deja_sin_clasificar(entorno, capsys):
    assert cli.main(["importar", str(FIXTURES / "tickets.json")]) == 0
    salida = capsys.readouterr()
    assert "OPENROUTER_API_KEY" in salida.err
    assert "Importados: 2. Saltados: 3." in salida.out
    assert {f["categoria"] for f in _filas(entorno.database_path, "tickets")} == {"sin_clasificar"}


def test_importar_fichero_inexistente(entorno, capsys):
    assert cli.main(["importar", "no-existe.csv"]) == 1
    assert "No existe" in capsys.readouterr().err


def test_importar_csv_sin_columna_texto(entorno, tmp_path, capsys):
    ruta = tmp_path / "malo.csv"
    ruta.write_text("asunto\nHola\n", encoding="utf-8")
    assert cli.main(["importar", str(ruta), "--sin-clasificar"]) == 1
    assert "columna «texto»" in capsys.readouterr().err
    assert not Path(entorno.database_path).exists()
