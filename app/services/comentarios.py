"""Comentarios internos de un ticket y su línea de tiempo (comentarios + cambios del ticket)."""

import sqlite3
from dataclasses import dataclass

from app.clock import Clock, to_iso
from app.services import auditoria

MAX_CARACTERES = 5000


class ComentarioInvalidoError(ValueError):
    """El texto de un comentario no es válido."""


@dataclass(frozen=True)
class Comentario:
    id: int
    ticket_id: int
    autor_id: int | None
    autor_nombre: str | None
    autor_email: str | None
    cuerpo: str
    creado_en: str


@dataclass(frozen=True)
class Entrada:
    """Un elemento de la línea de tiempo: un comentario o un cambio registrado en la auditoría."""

    tipo: str
    creado_en: str
    registro: auditoria.Registro | None = None
    comentario: Comentario | None = None


def normalizar(cuerpo: str) -> str:
    return cuerpo.replace("\r\n", "\n").replace("\r", "\n").strip()


def validar(cuerpo: str) -> str:
    """Devuelve el texto limpio o lanza ComentarioInvalidoError."""
    texto = normalizar(cuerpo)
    if not texto:
        raise ComentarioInvalidoError("Escribe un comentario antes de enviarlo.")
    if len(texto) > MAX_CARACTERES:
        raise ComentarioInvalidoError(
            f"El comentario no puede superar los {MAX_CARACTERES} caracteres (tiene {len(texto)})."
        )
    return texto


def crear_comentario(
    conn: sqlite3.Connection, ticket_id: int, autor_id: int, cuerpo: str, reloj: Clock
) -> int:
    """Guarda un comentario interno con su autor y fecha; devuelve su id."""
    texto = validar(cuerpo)
    cursor = conn.execute(
        "INSERT INTO comentarios (ticket_id, autor_id, cuerpo, interno, creado_en) "
        "VALUES (?, ?, ?, 1, ?)",
        (ticket_id, autor_id, texto, to_iso(reloj())),
    )
    conn.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def listar_comentarios(conn: sqlite3.Connection, ticket_id: int) -> list[Comentario]:
    filas = conn.execute(
        "SELECT c.id, c.ticket_id, c.autor_id, c.cuerpo, c.creado_en, "
        "u.nombre AS autor_nombre, u.email AS autor_email "
        "FROM comentarios c LEFT JOIN usuarios u ON u.id = c.autor_id "
        "WHERE c.ticket_id = ? ORDER BY c.creado_en, c.id",
        (ticket_id,),
    ).fetchall()
    return [
        Comentario(
            id=f["id"],
            ticket_id=f["ticket_id"],
            autor_id=f["autor_id"],
            autor_nombre=f["autor_nombre"],
            autor_email=f["autor_email"],
            cuerpo=f["cuerpo"],
            creado_en=f["creado_en"],
        )
        for f in filas
    ]


def linea_de_tiempo(conn: sqlite3.Connection, ticket_id: int) -> list[Entrada]:
    """Comentarios y cambios del ticket mezclados, del más antiguo al más reciente."""
    entradas = [
        Entrada(tipo="evento", creado_en=r.creado_en, registro=r)
        for r in auditoria.linea_de_tiempo(conn, ticket_id)
    ]
    entradas += [
        Entrada(tipo="comentario", creado_en=c.creado_en, comentario=c)
        for c in listar_comentarios(conn, ticket_id)
    ]
    # sort es estable: a igual fecha, cada grupo conserva su orden de inserción
    # y los cambios van antes que los comentarios.
    entradas.sort(key=lambda e: (e.creado_en, e.tipo != "evento"))
    return entradas
