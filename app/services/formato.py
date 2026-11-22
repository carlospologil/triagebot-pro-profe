"""Textos legibles para la interfaz."""

from datetime import UTC, datetime

ETIQUETAS_ESTADO = {
    "nuevo": "Nuevo",
    "en_curso": "En curso",
    "esperando_cliente": "Esperando al cliente",
    "resuelto": "Resuelto",
    "cerrado": "Cerrado",
}
ETIQUETAS_PRIORIDAD = {"baja": "Baja", "media": "Media", "alta": "Alta", "urgente": "Urgente"}
ETIQUETAS_CATEGORIA = {
    "facturacion": "Facturación",
    "tecnico": "Técnico",
    "cuenta": "Cuenta",
    "comercial": "Comercial",
    "envio": "Envío",
    "otro": "Otro",
    "sin_clasificar": "Sin clasificar",
}


def formatear_fecha(iso: str | None) -> str:
    """Devuelve una fecha ISO UTC como «02/03/2026 09:00 UTC»."""
    if not iso:
        return "—"
    momento = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
    return momento.strftime("%d/%m/%Y %H:%M") + " UTC"


def antiguedad(iso: str, ahora: datetime) -> str:
    """Devuelve la antigüedad de una fecha ISO UTC como «hace 3 h»."""
    momento = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    segundos = max(0, int((ahora - momento).total_seconds()))
    minutos = segundos // 60
    if minutos < 1:
        return "hace un momento"
    if minutos < 60:
        return f"hace {minutos} min"
    horas = minutos // 60
    if horas < 24:
        return f"hace {horas} h"
    dias = horas // 24
    if dias < 30:
        return f"hace {dias} d"
    if dias < 365:
        return f"hace {dias // 30} meses" if dias >= 60 else "hace 1 mes"
    anios = dias // 365
    return f"hace {anios} años" if anios > 1 else "hace 1 año"
