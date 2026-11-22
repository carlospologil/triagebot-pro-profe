"""Importación de tickets existentes desde ficheros CSV o JSON."""

import csv
import io
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.clock import Clock, system_clock
from app.schemas import TicketCrear
from app.services import tickets
from app.services.clasificador import CATEGORIA_SIN_CLASIFICAR

logger = logging.getLogger(__name__)

EMAIL_DESCONOCIDO = "sin-email@importado.invalid"
NOMBRE_DESCONOCIDO = "Sin identificar"
MAX_ASUNTO_AUTOMATICO = 80
DELIMITADORES = (",", ";", "\t")


class ImportacionError(ValueError):
    """El fichero no se puede leer o no tiene el formato esperado."""


@dataclass
class ResultadoImportacion:
    importados: int = 0
    sin_clasificar: int = 0
    saltados: list[str] = field(default_factory=list)


def _leer_texto(ruta: Path) -> str:
    try:
        return ruta.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ImportacionError(f"No existe el fichero «{ruta}».") from None
    except UnicodeDecodeError:
        raise ImportacionError("El fichero no está codificado en UTF-8.") from None
    except OSError as exc:
        raise ImportacionError(f"No se puede leer «{ruta}»: {exc.strerror or exc}.") from None


def _filas_csv(contenido: str) -> list[dict[str, Any]]:
    cabecera = contenido.splitlines()[0] if contenido.strip() else ""
    delimitador = max(DELIMITADORES, key=cabecera.count)
    try:
        filas = list(csv.reader(io.StringIO(contenido), delimiter=delimitador))
    except csv.Error as exc:
        raise ImportacionError(f"CSV mal formado: {exc}.") from None
    columnas = [c.strip().lower() for c in filas[0]] if filas else []
    if "texto" not in columnas:
        raise ImportacionError("El CSV debe tener una columna «texto».")
    return [
        dict(zip(columnas, fila, strict=False))
        for fila in filas[1:]
        if any(celda.strip() for celda in fila)
    ]


def _filas_json(contenido: str) -> list[Any]:
    try:
        datos = json.loads(contenido)
    except json.JSONDecodeError as exc:
        raise ImportacionError(f"JSON no válido: {exc}.") from None
    if not isinstance(datos, list):
        raise ImportacionError("El JSON debe ser una lista de objetos con la clave «texto».")
    return datos


def leer_filas(ruta: Path) -> list[Any]:
    """Filas del fichero según su extensión (.csv o .json)."""
    extension = ruta.suffix.lower()
    if extension not in (".csv", ".json"):
        raise ImportacionError("Formato no admitido: usa un fichero .csv o .json.")
    contenido = _leer_texto(ruta)
    return _filas_csv(contenido) if extension == ".csv" else _filas_json(contenido)


def _campo(fila: dict[str, Any], clave: str) -> str:
    valor = fila.get(clave)
    return "" if valor is None else str(valor).strip()


def _asunto_automatico(texto: str) -> str:
    primera_linea = texto.splitlines()[0].strip()
    if len(primera_linea) <= MAX_ASUNTO_AUTOMATICO:
        return primera_linea
    return primera_linea[: MAX_ASUNTO_AUTOMATICO - 1].rstrip() + "…"


def _preparar(fila: Any) -> TicketCrear | str:
    """El ticket a crear o, si la fila no sirve, el motivo por el que se salta."""
    if not isinstance(fila, dict):
        return "no es un objeto"
    texto = _campo(fila, "texto")
    if not texto:
        return "sin texto"
    email = _campo(fila, "email_cliente")
    try:
        return TicketCrear(
            asunto=_campo(fila, "asunto") or _asunto_automatico(texto),
            texto=texto,
            email_cliente=email or EMAIL_DESCONOCIDO,
            nombre_cliente=None if email else NOMBRE_DESCONOCIDO,
        )
    except ValidationError as exc:
        campo = ".".join(str(p) for p in exc.errors()[0]["loc"])
        return f"valor no válido en «{campo}»"


def importar_tickets(
    conn: sqlite3.Connection,
    filas: list[Any],
    cliente_llm: Any | None,
    clock: Clock = system_clock,
    *,
    clasificar: bool = True,
) -> ResultadoImportacion:
    """Crea un ticket por fila válida y, salvo que `clasificar` sea falso, lo clasifica.

    Las filas inválidas se saltan y se anota el motivo; si la IA falla, el ticket queda como
    `sin_clasificar`. Sin clasificar no se llama nunca al LLM.
    """
    resultado = ResultadoImportacion()
    for numero, fila in enumerate(filas, start=1):
        datos = _preparar(fila)
        if isinstance(datos, str):
            resultado.saltados.append(f"Fila {numero}: {datos}")
            continue
        ticket = tickets.crear_ticket(
            conn,
            datos,
            clock,
            categoria=None if clasificar else CATEGORIA_SIN_CLASIFICAR,
        )
        if clasificar:
            ticket = tickets.clasificar_ticket(
                conn, ticket.id, cliente_llm, clock, marcar_sin_clasificar=True
            )
        resultado.importados += 1
        if ticket.categoria == CATEGORIA_SIN_CLASIFICAR:
            resultado.sin_clasificar += 1
    return resultado
