"""Exportación de tickets a CSV pensado para abrirse en Excel."""

import csv
import io
import sqlite3
from collections.abc import Iterable

BOM_UTF8 = "﻿"
PREFIJOS_FORMULA = ("=", "+", "-", "@", "\t", "\r")

COLUMNAS: tuple[tuple[str, str], ...] = (
    ("id", "id"),
    ("asunto", "asunto"),
    ("texto", "descripcion"),
    ("nombre_cliente", "solicitante_nombre"),
    ("email_cliente", "solicitante_email"),
    ("estado", "estado"),
    ("prioridad", "prioridad"),
    ("categoria", "categoria"),
    ("asignado_a", "asignado_nombre"),
    ("creado_en", "creado_en"),
    ("actualizado_en", "actualizado_en"),
    ("fecha_limite", "fecha_limite"),
    ("resuelto_en", "resuelto_en"),
)


def _celda(valor: object) -> object:
    """Neutraliza las fórmulas (inyección CSV): Excel ejecutaría un texto que empiece por =, +…"""
    if isinstance(valor, str) and valor.startswith(PREFIJOS_FORMULA):
        return "'" + valor
    return "" if valor is None else valor


def tickets_a_csv(filas: Iterable[sqlite3.Row]) -> str:
    """CSV en UTF-8 con BOM (para que Excel respete tildes) y una fila por ticket."""
    salida = io.StringIO()
    escritor = csv.writer(salida, lineterminator="\r\n")
    escritor.writerow([nombre for nombre, _ in COLUMNAS])
    for fila in filas:
        escritor.writerow([_celda(fila[columna]) for _, columna in COLUMNAS])
    return BOM_UTF8 + salida.getvalue()
