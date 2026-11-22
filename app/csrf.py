"""Token CSRF ligado a la sesión: un valor aleatorio guardado en la cookie de sesión firmada."""

import hmac
import secrets
from collections.abc import MutableMapping

CSRF_SESSION_KEY = "csrf_token"
CSRF_FIELD = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"


def token_de_sesion(session: MutableMapping | None) -> str:
    """Devuelve el token de la sesión, creándolo si aún no existe ('' si no hay sesión)."""
    if session is None:
        return ""
    token = session.get(CSRF_SESSION_KEY)
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def token_valido(session: MutableMapping | None, recibido: str | None) -> bool:
    if session is None or not recibido:
        return False
    esperado = session.get(CSRF_SESSION_KEY)
    if not isinstance(esperado, str) or not esperado:
        return False
    return hmac.compare_digest(esperado.encode(), recibido.encode())
