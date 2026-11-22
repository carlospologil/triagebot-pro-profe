from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from markupsafe import Markup, escape

from app.csrf import CSRF_FIELD, token_de_sesion
from app.flash import recoger_flash

BASE_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(directory=BASE_DIR / "templates")


def _token(contexto) -> str:
    request = contexto.get("request")
    return token_de_sesion(request.scope.get("session") if request is not None else None)


@pass_context
def csrf_token(contexto) -> str:
    return _token(contexto)


@pass_context
def csrf_campo(contexto) -> Markup:
    """Campo oculto con el token CSRF para los formularios POST."""
    return Markup('<input type="hidden" name="{}" value="{}">').format(
        CSRF_FIELD, escape(_token(contexto))
    )


templates.env.globals["csrf_token"] = csrf_token
templates.env.globals["csrf_campo"] = csrf_campo


@pass_context
def mensajes_flash(contexto) -> list[tuple[str, str]]:
    request = contexto.get("request")
    return recoger_flash(request) if request is not None else []


@pass_context
def usuario_actual(contexto):
    """Usuario con sesión iniciada (None en páginas públicas o de error sin sesión)."""
    request = contexto.get("request")
    return getattr(request.state, "usuario", None) if request is not None else None


templates.env.globals["mensajes_flash"] = mensajes_flash
templates.env.globals["usuario_actual"] = usuario_actual
