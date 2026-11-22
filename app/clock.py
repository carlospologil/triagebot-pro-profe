"""Reloj inyectable: toda la aplicación obtiene la hora actual a través de aquí."""

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Request

Clock = Callable[[], datetime]


def system_clock() -> datetime:
    return datetime.now(UTC)


def get_clock(request: Request) -> Clock:
    """Dependencia de FastAPI: el reloj de la aplicación (sustituible en tests)."""
    return request.app.state.clock


def to_iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
