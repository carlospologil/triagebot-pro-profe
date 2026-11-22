"""Conjunto de datos conocido para comprobar las cifras del panel (ahora = 2026-03-02 09:00 UTC)."""

from app.services.usuarios import create_user

PASSWORD = "una-clave-segura"

# (estado, prioridad, categoria, agente, creado, fecha_limite, resuelto)
TICKETS = [
    # 1: vencido, sin asignar
    ("nuevo", "media", "facturacion", None, "2026-02-27T09:00:00Z", "2026-02-28T09:00:00Z", None),
    # 2: en plazo
    ("en_curso", "alta", "tecnico", "ana", "2026-03-02T08:00:00Z", "2026-03-02T12:00:00Z", None),
    # 3: vencido
    ("esperando_cliente", "baja", "tecnico", "luis", "2026-02-20T09:00:00Z",
     "2026-02-23T09:00:00Z", None),
    # 4: resuelto en 4 h (plazo ya pasado, pero resuelto: no cuenta como vencido)
    ("resuelto", "media", "cuenta", "ana", "2026-03-01T08:00:00Z", "2026-03-02T08:00:00Z",
     "2026-03-01T12:00:00Z"),
    # 5: cerrado en 12 h
    ("cerrado", "urgente", "otro", "ana", "2026-02-28T00:00:00Z", "2026-02-28T04:00:00Z",
     "2026-02-28T12:00:00Z"),
    # 6: resuelto en 8 h, hace más de 7 días, sin categoría
    ("resuelto", "baja", None, "luis", "2026-02-10T00:00:00Z", "2026-02-13T00:00:00Z",
     "2026-02-10T08:00:00Z"),
    # 7: resuelto en 1 h
    ("resuelto", "media", "facturacion", "luis", "2026-03-02T07:00:00Z", "2026-03-03T07:00:00Z",
     "2026-03-02T08:00:00Z"),
    # 8: resuelto en 6 h, sin asignar
    ("resuelto", "media", "sin_clasificar", None, "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z",
     "2026-03-01T06:00:00Z"),
    # 9: resuelto en 4 h, justo hace 7 días (el límite entra en la ventana)
    ("resuelto", "baja", "comercial", "luis", "2026-02-23T05:00:00Z", "2026-02-26T05:00:00Z",
     "2026-02-23T09:00:00Z"),
]  # fmt: skip


def cargar_datos(db) -> dict[str, int]:
    """Inserta usuarios y tickets de ejemplo; devuelve los ids de usuario por clave."""
    ids = {
        "ana": create_user(db, email="ana@example.com", nombre="Ana", password=PASSWORD).id,
        "luis": create_user(db, email="luis@example.com", nombre="Luis", password=PASSWORD).id,
        "eva": create_user(db, email="eva@example.com", nombre="Eva", password=PASSWORD).id,
        "admin": create_user(
            db, email="admin@example.com", nombre="Dirección", password=PASSWORD, rol="admin"
        ).id,
    }
    inactivo = create_user(db, email="baja@example.com", nombre="Baja", password=PASSWORD)
    db.execute("UPDATE usuarios SET activo = 0 WHERE id = ?", (inactivo.id,))
    for i, (estado, prioridad, categoria, agente, creado, limite, resuelto) in enumerate(
        TICKETS, start=1
    ):
        db.execute(
            "INSERT INTO tickets (asunto, descripcion, solicitante_nombre, solicitante_email, "
            "estado, prioridad, categoria, asignado_a, fecha_limite, creado_en, actualizado_en, "
            "resuelto_en) "
            "VALUES (?, 'Texto', 'Laura', 'laura@example.com', ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"Ticket {i}", estado, prioridad, categoria, ids.get(agente), limite, creado,
             creado, resuelto),
        )  # fmt: skip
    db.commit()
    return ids
