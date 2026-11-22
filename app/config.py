"""Configuración de la aplicación, leída únicamente de variables de entorno."""

import os
from collections.abc import Mapping
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """Error de configuración (variable de entorno ausente o inválida)."""


@dataclass(frozen=True)
class Settings:
    secret_key: str
    database_path: str = "triagebot.db"
    openrouter_api_key: str = ""


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    secret_key = env.get("SECRET_KEY", "").strip()
    if not secret_key:
        raise ConfigError(
            "Falta la variable de entorno SECRET_KEY. Defínela (por ejemplo, "
            "copia .env.example a .env y exporta sus valores) antes de arrancar "
            "TriageBot Pro."
        )
    return Settings(
        secret_key=secret_key,
        database_path=env.get("DATABASE_PATH", "").strip() or "triagebot.db",
        openrouter_api_key=env.get("OPENROUTER_API_KEY", "").strip(),
    )
