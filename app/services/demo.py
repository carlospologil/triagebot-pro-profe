"""Datos de demostración: usuarios y tickets variados, sin llamar al LLM."""

import random
import sqlite3
from datetime import timedelta

from app.clock import Clock, system_clock, to_iso
from app.services import auditoria, sla
from app.services.formato import ETIQUETAS_CATEGORIA
from app.services.usuarios import UsuarioError, create_user

TOTAL_TICKETS = 60
SEMILLA = 2026

USUARIOS_DEMO = (
    ("admin@triagebot.demo", "Alicia Admin", "admin", "demo-admin-2026"),
    ("marta@triagebot.demo", "Marta Ruiz", "agente", "demo-marta-2026"),
    ("diego@triagebot.demo", "Diego Salas", "agente", "demo-diego-2026"),
    ("lucia@triagebot.demo", "Lucía Prado", "agente", "demo-lucia-2026"),
)

CLIENTES = (
    ("Carmen Ortiz", "carmen.ortiz@ejemplo.com"),
    ("Javier Molina", "javier.molina@ejemplo.com"),
    ("Elena Navarro", "elena.navarro@ejemplo.com"),
    ("Pablo Serrano", "pablo.serrano@ejemplo.com"),
    ("Sofía Vidal", "sofia.vidal@ejemplo.com"),
    ("Andrés Gil", "andres.gil@ejemplo.com"),
)

ASUNTOS = {
    "facturacion": ("Cobro duplicado en mi factura", "Me han cobrado dos veces el último mes."),
    "tecnico": (
        "La aplicación se cierra al abrir informes",
        "Al abrir un informe la app se cierra.",
    ),
    "cuenta": ("No puedo restablecer mi contraseña", "El correo de recuperación nunca llega."),
    "comercial": ("Quiero ampliar mi plan", "Necesitamos más puestos; ¿qué opciones hay?"),
    "envio": ("Mi pedido no ha llegado", "Han pasado diez días y el pedido sigue sin llegar."),
    "otro": (
        "Duda sobre la política de privacidad",
        "¿Dónde puedo consultar cómo tratan mis datos?",
    ),
}
ESTADOS = ("nuevo", "en_curso", "esperando_cliente", "resuelto", "cerrado")
PESOS_ESTADO = (14, 16, 8, 12, 10)
PRIORIDADES = ("baja", "media", "alta", "urgente")
PESOS_PRIORIDAD = (10, 25, 15, 10)
NOTAS = (
    "He contactado con el cliente para pedirle más detalles.",
    "Escalado al equipo responsable; seguimos el caso.",
    "Pendiente de confirmar la solución con el cliente.",
)


def hay_datos_demo(conn: sqlite3.Connection) -> bool:
    fila = conn.execute(
        "SELECT 1 FROM usuarios WHERE email = ?", (USUARIOS_DEMO[0][0],)
    ).fetchone()
    return fila is not None


def crear_datos_demo(conn: sqlite3.Connection, clock: Clock = system_clock) -> list[tuple]:
    """Crea 1 admin, 3 agentes y 60 tickets; devuelve las credenciales (email, rol, contraseña)."""
    if hay_datos_demo(conn):
        raise UsuarioError("Ya existen los datos de demostración en esta base de datos.")
    usuarios = [
        create_user(conn, email=e, nombre=n, password=p, rol=r, clock=clock)
        for e, n, r, p in USUARIOS_DEMO
    ]
    agentes = [u.id for u in usuarios if u.rol == "agente"]
    azar = random.Random(SEMILLA)
    ahora = clock()
    categorias = [c for c in ETIQUETAS_CATEGORIA if c != "sin_clasificar"]
    for i in range(TOTAL_TICKETS):
        categoria = categorias[i % len(categorias)]
        asunto, texto = ASUNTOS[categoria]
        nombre, email = azar.choice(CLIENTES)
        estado = azar.choices(ESTADOS, PESOS_ESTADO)[0]
        prioridad = azar.choices(PRIORIDADES, PESOS_PRIORIDAD)[0]
        creado = ahora - timedelta(hours=azar.randint(1, 24 * 30))
        creado_iso = to_iso(creado)
        actualizado = creado + timedelta(hours=azar.randint(0, 48))
        actualizado = min(actualizado, ahora)
        resuelto = to_iso(actualizado) if estado in ("resuelto", "cerrado") else None
        asignado = None if estado == "nuevo" and i % 2 else azar.choice(agentes)
        cursor = conn.execute(
            "INSERT INTO tickets (asunto, descripcion, solicitante_nombre, solicitante_email, "
            "estado, prioridad, categoria, resumen_ia, asignado_a, fecha_limite, creado_en, "
            "actualizado_en, resuelto_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"{asunto} ({i + 1})",
                texto,
                nombre,
                email,
                estado,
                prioridad,
                categoria,
                f"Clasificado como {ETIQUETAS_CATEGORIA[categoria].lower()} "
                f"de prioridad {prioridad}.",
                asignado,
                sla.calcular_fecha_limite(creado_iso, prioridad),
                creado_iso,
                to_iso(actualizado),
                resuelto,
            ),
        )
        ticket_id = cursor.lastrowid
        auditoria.registrar(
            conn,
            auditoria.TICKET_CREADO,
            ahora=creado_iso,
            ticket_id=ticket_id,
            valor_nuevo=f"{asunto} ({i + 1})",
        )
        if asignado is not None and estado != "nuevo":
            conn.execute(
                "INSERT INTO comentarios (ticket_id, autor_id, cuerpo, interno, creado_en) "
                "VALUES (?, ?, ?, 1, ?)",
                (ticket_id, asignado, azar.choice(NOTAS), to_iso(actualizado)),
            )
    conn.commit()
    return [(u.email, u.rol, p) for u, (_, _, _, p) in zip(usuarios, USUARIOS_DEMO, strict=True)]
