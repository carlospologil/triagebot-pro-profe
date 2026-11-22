import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.clock import Clock, get_clock
from app.db import get_db
from app.services.formato import ETIQUETAS_CATEGORIA, ETIQUETAS_ESTADO, ETIQUETAS_PRIORIDAD
from app.services.graficos import barras_svg
from app.services.metricas import calcular_metricas
from app.templating import templates

router = APIRouter()

Db = Annotated[sqlite3.Connection, Depends(get_db)]
RelojDep = Annotated[Clock, Depends(get_clock)]


def _horas(valor: float | None) -> str:
    if valor is None:
        return "—"
    return f"{valor:.1f}".replace(".", ",") + " h"


@router.get("/panel", response_class=HTMLResponse)
def panel(request: Request, conn: Db, reloj: RelojDep):
    metricas = calcular_metricas(conn, reloj)
    graficos = [
        (
            "Tickets por estado",
            barras_svg(
                [(ETIQUETAS_ESTADO[k], v) for k, v in metricas.por_estado.items()],
                "Tickets por estado",
            ),
        ),
        (
            "Tickets por categoría",
            barras_svg(
                [(ETIQUETAS_CATEGORIA[k], v) for k, v in metricas.por_categoria.items()],
                "Tickets por categoría",
            ),
        ),
        (
            "Tickets por prioridad",
            barras_svg(
                [(ETIQUETAS_PRIORIDAD[k], v) for k, v in metricas.por_prioridad.items()],
                "Tickets por prioridad",
            ),
        ),
    ]
    titulo_agentes = f"Resueltos por agente (últimos {metricas.dias_ventana} días)"
    grafico_agentes = barras_svg(
        [(a.nombre, a.resueltos) for a in metricas.resueltos_por_agente], titulo_agentes
    )
    contexto = {
        "usuario": request.state.usuario,
        "metricas": metricas,
        "graficos": graficos,
        "titulo_agentes": titulo_agentes,
        "grafico_agentes": grafico_agentes,
        "tiempo_medio": _horas(metricas.tiempo_medio_resolucion_horas),
    }
    return templates.TemplateResponse(request, "panel.html", contexto)
