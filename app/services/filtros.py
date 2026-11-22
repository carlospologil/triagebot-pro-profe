"""Filtros de la bandeja, compartidos por la página y por la exportación a CSV."""

from dataclasses import dataclass

from app.services.formato import ETIQUETAS_CATEGORIA, ETIQUETAS_ESTADO, ETIQUETAS_PRIORIDAD
from app.services.tickets import SIN_ASIGNAR

MAX_ENTERO_SQLITE = 2**63 - 1


@dataclass(frozen=True)
class FiltrosBandeja:
    estado: str | None
    categoria: str | None
    prioridad: str | None
    asignado_a: int | str | None
    q: str
    solo_mios: bool
    solo_vencidos: bool


def _opcion(valor: str, validos: tuple[str, ...]) -> str | None:
    """Un filtro vacío o desconocido equivale a «sin filtrar»."""
    valor = valor.strip()
    return valor if valor in validos else None


def entero(valor: str, minimo: int) -> int | None:
    try:
        numero = int(valor)
    except ValueError:
        return None
    return numero if minimo <= numero <= MAX_ENTERO_SQLITE else None


def interpretar_filtros(
    *,
    usuario_id: int,
    estado: str = "",
    categoria: str = "",
    prioridad: str = "",
    asignado_a: str = "",
    mios: str = "",
    vencidos: str = "",
    q: str = "",
) -> FiltrosBandeja:
    """Convierte los parámetros de la URL (siempre texto) en filtros válidos y tolerantes."""
    solo_mios = mios == "1"
    asignado: int | str | None
    if solo_mios:
        asignado = usuario_id
    elif asignado_a == SIN_ASIGNAR:
        asignado = SIN_ASIGNAR
    else:
        asignado = entero(asignado_a, 1)
    return FiltrosBandeja(
        estado=_opcion(estado, tuple(ETIQUETAS_ESTADO)),
        categoria=_opcion(categoria, tuple(ETIQUETAS_CATEGORIA)),
        prioridad=_opcion(prioridad, tuple(ETIQUETAS_PRIORIDAD)),
        asignado_a=asignado,
        q=q.strip(),
        solo_mios=solo_mios,
        solo_vencidos=vencidos == "1",
    )
