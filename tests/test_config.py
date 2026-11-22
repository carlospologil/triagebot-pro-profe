import pytest

from app.config import ConfigError, load_settings


def test_lee_todas_las_variables():
    settings = load_settings(
        {"SECRET_KEY": "s", "DATABASE_PATH": "/tmp/x.db", "OPENROUTER_API_KEY": "k"}
    )
    assert settings.secret_key == "s"
    assert settings.database_path == "/tmp/x.db"
    assert settings.openrouter_api_key == "k"


def test_valores_por_defecto():
    settings = load_settings({"SECRET_KEY": "s"})
    assert settings.database_path == "triagebot.db"
    assert settings.openrouter_api_key == ""


@pytest.mark.parametrize("environ", [{}, {"SECRET_KEY": ""}, {"SECRET_KEY": "   "}])
def test_falla_sin_secret_key(environ):
    with pytest.raises(ConfigError, match="SECRET_KEY"):
        load_settings(environ)


def test_usa_os_environ_por_defecto(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "desde-entorno")
    assert load_settings().secret_key == "desde-entorno"
    monkeypatch.delenv("SECRET_KEY")
    with pytest.raises(ConfigError):
        load_settings()
