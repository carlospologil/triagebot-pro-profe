"""Modelos Pydantic de entrada y salida de la API."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Estado = Literal["nuevo", "en_progreso", "pendiente", "resuelto", "cerrado"]
Prioridad = Literal["baja", "media", "alta", "urgente"]
Categoria = Literal[
    "facturacion", "tecnico", "cuenta", "comercial", "envio", "otro", "sin_clasificar"
]

ESTADOS_FINALES: tuple[str, ...] = ("resuelto", "cerrado")

Texto = Annotated[str, StringConstraints(strip_whitespace=True)]
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]


class TicketCrear(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "asunto": "No puedo acceder a mi factura",
                "texto": "Al pulsar en «Descargar» aparece un error 500.",
                "email_cliente": "cliente@example.com",
                "nombre_cliente": "Laura Gómez",
            }
        }
    )

    asunto: Texto = Field(min_length=1, max_length=200, description="Asunto del ticket.")
    texto: Texto = Field(min_length=1, max_length=20000, description="Descripción del problema.")
    email_cliente: Email = Field(description="Email de la persona solicitante.")
    nombre_cliente: Texto | None = Field(
        default=None,
        max_length=120,
        description="Nombre de la persona solicitante (si se omite, se usa su email).",
    )


class TicketActualizar(BaseModel):
    """Cambios parciales: solo se modifican los campos enviados."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"estado": "en_progreso", "asignado_a": 2}},
    )

    estado: Estado | None = None
    prioridad: Prioridad | None = None
    categoria: Categoria | None = Field(default=None, description="null quita la categoría.")
    asignado_a: int | None = Field(
        default=None, ge=1, description="Id del usuario asignado; null desasigna."
    )

    @field_validator("estado", "prioridad")
    @classmethod
    def _no_nulo(cls, valor, info):
        if valor is None:
            raise ValueError(f"{info.field_name} no puede ser nulo")
        return valor


class TicketSalida(BaseModel):
    id: int
    asunto: str
    texto: str
    email_cliente: str
    nombre_cliente: str
    estado: Estado
    prioridad: Prioridad
    categoria: Categoria | None
    resumen_ia: str | None
    asignado_a: int | None
    fecha_limite: str | None
    creado_en: str
    actualizado_en: str
    resuelto_en: str | None


class PaginaTickets(BaseModel):
    items: list[TicketSalida]
    total: int = Field(description="Tickets que cumplen los filtros, sin paginar.")
    page: int
    page_size: int
    paginas: int = Field(description="Número total de páginas.")
