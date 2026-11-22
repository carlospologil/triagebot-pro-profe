"""Métricas de soporte para el panel de dirección."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.clock import Clock, system_clock, to_iso
from app.schemas import ESTADOS_FINALES
from app.services.formato import ETIQUETAS_CATEGORIA, ETIQUETAS_ESTADO, ETIQUETAS_PRIORIDAD

DIAS_VENTANA = 7
FORMATO_ISO = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class ResueltosAgente:
    agente_id: int
    nombre: str
    resueltos: int


@dataclass(frozen=True)
class Metricas:
    total: int
    por_estado: dict[str, int]
    por_categoria: dict[str, int]
    por_prioridad: dict[str, int]
    vencidos: int
    tiempo_medio_resolucion_horas: float | None
    resueltos_por_agente: list[ResueltosAgente]
    dias_ventana: int = DIAS_VENTANA


def _contar_por(conn: sqlite3.Connection, columna: str, claves: dict[str, str]) -> dict[str, int]:
    """Cuenta tickets por `columna` con todas las claves conocidas (a 0 si no hay ninguno)."""
    conteo = dict.fromkeys(claves, 0)
    filas = conn.execute(f"SELECT {columna} AS clave, COUNT(*) AS n FROM tickets GROUP BY 1")
    for fila in filas:
        clave = fila["clave"]
        if clave is None and "sin_clasificar" in conteo:
            clave = "sin_clasificar"
        conteo[clave] = conteo.get(clave, 0) + fila["n"]
    return conteo


def _tiempo_medio_horas(conn: sqlite3.Connection) -> float | None:
    marcas = ", ".join("?" * len(ESTADOS_FINALES))
    filas = conn.execute(
        f"SELECT creado_en, resuelto_en FROM tickets "
        f"WHERE resuelto_en IS NOT NULL AND estado IN ({marcas})",
        ESTADOS_FINALES,
    ).fetchall()
    duraciones = []
    for fila in filas:
        try:
            creado = datetime.strptime(fila["creado_en"], FORMATO_ISO)
            resuelto = datetime.strptime(fila["resuelto_en"], FORMATO_ISO)
        except ValueError:
            continue
        duraciones.append((resuelto - creado).total_seconds())
    if not duraciones:
        return None
    return sum(duraciones) / len(duraciones) / 3600


def _resueltos_por_agente(conn: sqlite3.Connection, desde: str) -> list[ResueltosAgente]:
    marcas = ", ".join("?" * len(ESTADOS_FINALES))
    filas = conn.execute(
        f"""
        SELECT u.id AS id, u.nombre AS nombre, COUNT(t.id) AS n
        FROM usuarios u
        LEFT JOIN tickets t
            ON t.asignado_a = u.id
            AND t.estado IN ({marcas})
            AND t.resuelto_en IS NOT NULL
            AND t.resuelto_en >= ?
        WHERE (u.activo = 1 AND u.rol = 'agente') OR t.id IS NOT NULL
        GROUP BY u.id
        ORDER BY n DESC, u.nombre, u.id
        """,  # noqa: S608
        [*ESTADOS_FINALES, desde],
    ).fetchall()
    return [ResueltosAgente(f["id"], f["nombre"], f["n"]) for f in filas]


def calcular_metricas(conn: sqlite3.Connection, clock: Clock = system_clock) -> Metricas:
    """Cifras del panel: totales, vencidos, tiempo medio de resolución y resueltos por agente.

    - Vencidos: tickets sin resolver ni cerrar con la fecha límite ya superada.
    - Tiempo medio: horas entre creación y resolución de los tickets resueltos o cerrados.
    - Resueltos por agente: tickets resueltos o cerrados en los últimos 7 días, por asignado.
    """
    ahora = clock().astimezone(UTC)
    marcas = ", ".join("?" * len(ESTADOS_FINALES))
    vencidos = conn.execute(
        f"SELECT COUNT(*) FROM tickets WHERE estado NOT IN ({marcas}) AND fecha_limite < ?",
        [*ESTADOS_FINALES, to_iso(ahora)],
    ).fetchone()[0]
    return Metricas(
        total=conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0],
        por_estado=_contar_por(conn, "estado", ETIQUETAS_ESTADO),
        por_categoria=_contar_por(conn, "categoria", ETIQUETAS_CATEGORIA),
        por_prioridad=_contar_por(conn, "prioridad", ETIQUETAS_PRIORIDAD),
        vencidos=vencidos,
        tiempo_medio_resolucion_horas=_tiempo_medio_horas(conn),
        resueltos_por_agente=_resueltos_por_agente(
            conn, to_iso(ahora - timedelta(days=DIAS_VENTANA))
        ),
    )
