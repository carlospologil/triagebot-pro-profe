"""Plazos (SLA) de los tickets según su prioridad y detección de vencimientos."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.schemas import ESTADOS_FINALES

FORMATO_ISO = "%Y-%m-%dT%H:%M:%SZ"

# La prioridad «urgente» no tiene plazo propio en el requisito: se trata como «alta».
PLAZOS_HORAS = {"urgente": 4, "alta": 4, "media": 24, "baja": 72}
PLAZO_POR_DEFECTO_HORAS = PLAZOS_HORAS["media"]


@dataclass(frozen=True)
class Plazo:
    vencido: bool
    texto: str


def _parsear(iso: str) -> datetime:
    return datetime.strptime(iso, FORMATO_ISO).replace(tzinfo=UTC)


def calcular_fecha_limite(creado_en: str, prioridad: str) -> str:
    """Fecha límite (ISO UTC): creación del ticket más el plazo de su prioridad."""
    horas = PLAZOS_HORAS.get(prioridad, PLAZO_POR_DEFECTO_HORAS)
    return (_parsear(creado_en) + timedelta(hours=horas)).strftime(FORMATO_ISO)


def esta_vencido(fecha_limite: str | None, estado: str, ahora: datetime) -> bool:
    """Vencido: sin resolver ni cerrar y con la fecha límite ya superada."""
    if not fecha_limite or estado in ESTADOS_FINALES:
        return False
    return ahora > _parsear(fecha_limite)


def _duracion(segundos: int) -> str:
    minutos = segundos // 60
    if minutos < 1:
        return "menos de 1 min"
    if minutos < 60:
        return f"{minutos} min"
    horas, resto = divmod(minutos, 60)
    if horas < 24:
        return f"{horas} h {resto} min" if resto else f"{horas} h"
    dias, horas = divmod(horas, 24)
    return f"{dias} d {horas} h" if horas else f"{dias} d"


def calcular_plazo(fecha_limite: str | None, estado: str, ahora: datetime) -> Plazo | None:
    """Estado del plazo para mostrarlo; None si no hay plazo o el ticket ya está terminado."""
    if not fecha_limite or estado in ESTADOS_FINALES:
        return None
    segundos = int((_parsear(fecha_limite) - ahora).total_seconds())
    if segundos < 0:
        return Plazo(vencido=True, texto=f"Excedido por {_duracion(-segundos)}")
    return Plazo(vencido=False, texto=f"Quedan {_duracion(segundos)}")


def rellenar_fechas_limite(conn: sqlite3.Connection) -> int:
    """Calcula la fecha límite de los tickets anteriores a esta funcionalidad que no la tienen."""
    filas = conn.execute(
        "SELECT id, creado_en, prioridad FROM tickets WHERE fecha_limite IS NULL"
    ).fetchall()
    for fila in filas:
        try:
            limite = calcular_fecha_limite(fila["creado_en"], fila["prioridad"])
        except ValueError:
            continue
        conn.execute("UPDATE tickets SET fecha_limite = ? WHERE id = ?", (limite, fila["id"]))
    conn.commit()
    return len(filas)
