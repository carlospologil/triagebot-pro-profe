from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.permisos import require_role
from app.services.usuarios import Usuario
from app.templating import templates

solo_admin = require_role("admin")

# La dependencia a nivel de router protege también las rutas /admin que se añadan después.
router = APIRouter(prefix="/admin", dependencies=[Depends(solo_admin)])


@router.get("", response_class=HTMLResponse)
def panel(request: Request, usuario: Annotated[Usuario, Depends(solo_admin)]):
    return templates.TemplateResponse(request, "admin.html", {"usuario": usuario})
