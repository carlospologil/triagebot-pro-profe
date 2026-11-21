from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.templating import templates

router = APIRouter()


@router.get("/", include_in_schema=False)
def inicio():
    return RedirectResponse("/bandeja", status_code=303)


@router.get("/bandeja", response_class=HTMLResponse)
def bandeja(request: Request):
    return templates.TemplateResponse(request, "bandeja.html", {"usuario": request.state.usuario})
