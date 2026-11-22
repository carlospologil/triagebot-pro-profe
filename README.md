# TriageBot Pro

[![CI](https://github.com/carlospologil/triagebot-pro-profe/actions/workflows/ci.yml/badge.svg)](https://github.com/carlospologil/triagebot-pro-profe/actions/workflows/ci.yml)

Aplicación web interna para que un equipo de soporte reciba tickets, los clasifique con IA,
los asigne, los resuelva dentro de plazo y mida su rendimiento.

Stack: Python 3.12, FastAPI, Pydantic v2, SQLite (`sqlite3`, sin ORM), Jinja2 + HTMX 2,
CSS propio y OpenRouter (modelo `openai/gpt-oss-120b`) para la clasificación.

## Funcionalidades

- **Recepción de tickets** por API (`POST /api/tickets`) o por importación de ficheros CSV/JSON.
- **Clasificación con IA**: categoría y prioridad propuestas por el modelo; el agente puede
  corregirlas a mano. Si la IA falla, el ticket queda como `sin_clasificar`.
- **Bandeja** con filtros, búsqueda y paginación, actualizada con HTMX.
- **Detalle del ticket**: cambio de estado, asignación a agentes, reclasificación,
  comentarios internos y línea de tiempo con el historial completo.
- **Plazos (SLA)** según prioridad (urgente/alta 4 h, media 24 h, baja 72 h) con aviso de
  tickets vencidos.
- **Panel de dirección** con métricas (totales, vencidos, tiempo medio de resolución,
  resueltos por agente) y gráficos.
- **Importación y exportación**: CSV/JSON de entrada y exportación CSV
  (`GET /api/tickets/export.csv`).
- **Usuarios y roles** (admin y agente): inicio de sesión, cambio de contraseña, alta,
  cambio de rol, desactivación y restablecimiento desde el área de administración.
- **Auditoría** de las acciones relevantes, visible para administradores.
- **Seguridad**: contraseñas con hash, sesiones firmadas, protección CSRF, cabeceras de
  seguridad y consultas SQL parametrizadas.
- **Datos de demostración** para probar el producto sin llamar a la IA.

## Demo en tres comandos

```bash
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
export SECRET_KEY=clave-local-de-demo && .venv/bin/python -m app.cli demo
.venv/bin/python -m uvicorn app.main:app
```

Abre <http://127.0.0.1:8000> e inicia sesión con alguna de las credenciales que imprime el
segundo comando (por ejemplo `admin@triagebot.demo` / `demo-admin-2026`).

## Configuración

Toda la configuración se hace con variables de entorno (ver `.env.example`):

| Variable             | Obligatoria | Descripción                                           |
| -------------------- | ----------- | ----------------------------------------------------- |
| `SECRET_KEY`         | Sí          | Clave para firmar las sesiones.                       |
| `DATABASE_PATH`      | No          | Ruta del fichero SQLite (por defecto `triagebot.db`). |
| `OPENROUTER_API_KEY` | No*         | Clave de OpenRouter para la clasificación con IA.     |

\* Necesaria solo para clasificar tickets con IA.

```bash
cp .env.example .env      # edita los valores
set -a; source .env; set +a
```

Si falta `SECRET_KEY`, la aplicación no arranca y muestra un mensaje de error claro.

## Línea de comandos

```bash
.venv/bin/python -m app.cli crear-admin --email ana@empresa.com --nombre "Ana"
.venv/bin/python -m app.cli importar tickets.csv [--sin-clasificar]
.venv/bin/python -m app.cli demo
```

## Calidad

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q
```

Los tests nunca usan la red ni claves reales: el cliente LLM se inyecta como dependencia y
en los tests se sustituye por uno falso; cada test usa una base de datos temporal y un reloj
inyectable. El workflow de GitHub Actions (`.github/workflows/ci.yml`) ejecuta ruff y pytest
con Python 3.12 en cada push y pull request, sin necesitar secretos.

## Estructura del código

```
app/
  main.py          create_app(): middlewares, routers y manejo de errores
  config.py        configuración por variables de entorno
  db.py            conexión SQLite y migraciones
  auth.py          hash y verificación de contraseñas
  cli.py           comandos: crear-admin, importar, demo
  clock.py         reloj inyectable
  csrf.py, seguridad.py, middleware.py, permisos.py   seguridad y control de acceso
  routers/         endpoints HTTP (bandeja, detalle, panel, admin, cuenta, API de tickets...)
  services/        lógica de negocio (tickets, clasificador, sla, metricas, importacion,
                   exportacion, comentarios, usuarios, auditoria, demo...)
  templates/       plantillas Jinja2 (parciales HTMX incluidas)
  static/          CSS propio
tests/             un fichero de test por módulo
  fixtures/        ficheros de ejemplo (CSV, JSON)
.github/workflows/ci.yml   integración continua
```
