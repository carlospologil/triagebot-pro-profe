"""Mensajes flash: avisos de una sola lectura guardados en la sesión."""

from starlette.requests import Request

CLAVE_FLASH = "mensajes_flash"
TIPOS = ("ok", "error", "aviso")


def flash(request: Request, texto: str, tipo: str = "ok") -> None:
    """Deja un mensaje para la próxima página que se pinte (tras redirigir o no)."""
    if tipo not in TIPOS:
        raise ValueError(f"Tipo de mensaje desconocido: {tipo}")
    pendientes = request.session.get(CLAVE_FLASH)
    if not isinstance(pendientes, list):
        pendientes = []
    request.session[CLAVE_FLASH] = [*pendientes, [tipo, texto]]


def recoger_flash(request: Request) -> list[tuple[str, str]]:
    """Devuelve los mensajes pendientes y los borra de la sesión."""
    session = request.scope.get("session")
    if session is None:
        return []
    pendientes = session.pop(CLAVE_FLASH, None)
    if not isinstance(pendientes, list):
        return []
    return [(str(p[0]), str(p[1])) for p in pendientes if isinstance(p, list) and len(p) == 2]
