"""Endurecimiento HTTP: cabeceras de seguridad en todas las respuestas y protección CSRF."""

from urllib.parse import parse_qs

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.csrf import CSRF_FIELD, CSRF_HEADER, token_valido
from app.templating import templates

CABECERAS_SEGURIDAD = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' https://unpkg.com; style-src 'self'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; "
        "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}

METODOS_SEGUROS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
TIPO_FORMULARIO = "application/x-www-form-urlencoded"
MAX_CUERPO_FORMULARIO = 1024 * 1024
MENSAJE_CSRF = "Falta el token de seguridad o ha caducado. Recarga la página e inténtalo de nuevo."


def aplicar_cabeceras_seguridad(headers: MutableHeaders) -> None:
    for nombre, valor in CABECERAS_SEGURIDAD.items():
        headers[nombre] = valor


class CabecerasSeguridadMiddleware:
    """Añade las cabeceras de seguridad a todas las respuestas HTTP."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def enviar(message: Message) -> None:
            if message["type"] == "http.response.start":
                aplicar_cabeceras_seguridad(MutableHeaders(scope=message))
            await send(message)

        await self.app(scope, receive, enviar)


class CsrfMiddleware:
    """Exige un token CSRF válido (cabecera X-CSRF-Token o campo de formulario) en toda
    petición que modifica datos. Debe ir dentro de SessionMiddleware."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in METODOS_SEGUROS:
            await self.app(scope, receive, send)
            return

        session = scope.get("session")
        headers = Headers(scope=scope)
        recibido = headers.get(CSRF_HEADER)
        if recibido is None and headers.get("content-type", "").split(";")[0].strip() == (
            TIPO_FORMULARIO
        ):
            cuerpo = await _leer_cuerpo(receive)
            if cuerpo is None:
                await self._rechazar(scope, receive, send, 413, "La petición es demasiado grande.")
                return
            campos = parse_qs(cuerpo.decode("utf-8", "replace"), keep_blank_values=True)
            recibido = (campos.get(CSRF_FIELD) or [None])[0]
            receive = _reproducir(cuerpo, receive)

        if not token_valido(session, recibido):
            await self._rechazar(scope, receive, send, 403, MENSAJE_CSRF)
            return
        await self.app(scope, receive, send)

    @staticmethod
    async def _rechazar(scope: Scope, receive: Receive, send: Send, status: int, mensaje: str):
        request = Request(scope, receive)
        if request.url.path == "/api" or request.url.path.startswith("/api/"):
            respuesta = JSONResponse({"detail": mensaje}, status_code=status)
        else:
            respuesta = templates.TemplateResponse(
                request, "prohibido.html", {"mensaje": mensaje}, status_code=status
            )
        await respuesta(scope, receive, send)


async def _leer_cuerpo(receive: Receive) -> bytes | None:
    """Lee el cuerpo completo; devuelve None si supera el máximo permitido."""
    trozos: list[bytes] = []
    total = 0
    while True:
        mensaje = await receive()
        if mensaje["type"] != "http.request":
            return b"".join(trozos)
        trozos.append(mensaje.get("body", b""))
        total += len(trozos[-1])
        if total > MAX_CUERPO_FORMULARIO:
            return None
        if not mensaje.get("more_body", False):
            return b"".join(trozos)


def _reproducir(cuerpo: bytes, receive: Receive) -> Receive:
    enviado = False

    async def reproducir() -> Message:
        nonlocal enviado
        if not enviado:
            enviado = True
            return {"type": "http.request", "body": cuerpo, "more_body": False}
        return await receive()

    return reproducir
