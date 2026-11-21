# TriageBot Pro

Aplicación web interna para que un equipo de soporte reciba tickets, los clasifique con IA,
los asigne, los resuelva dentro de plazo y mida su rendimiento.

Stack: Python 3.12+, FastAPI, Pydantic v2, SQLite (`sqlite3`), Jinja2 + HTMX, OpenRouter.

## Instalación

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## Configuración

Toda la configuración se hace con variables de entorno (ver `.env.example`):

| Variable             | Obligatoria | Descripción                                         |
| -------------------- | ----------- | --------------------------------------------------- |
| `SECRET_KEY`         | Sí          | Clave para firmar las sesiones.                     |
| `DATABASE_PATH`      | No          | Ruta del fichero SQLite (por defecto `triagebot.db`). |
| `OPENROUTER_API_KEY` | No*         | Clave de OpenRouter para la clasificación con IA.   |

\* Necesaria solo para clasificar tickets con IA.

```bash
cp .env.example .env      # edita los valores
set -a; source .env; set +a
```

Si falta `SECRET_KEY`, la aplicación no arranca y muestra un mensaje de error claro.

## Arranque

```bash
.venv/bin/python -m uvicorn app.main:app --reload
```

Comprueba que funciona en <http://127.0.0.1:8000/health>, que devuelve `{"status": "ok"}`.

## Calidad

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q
```

Los tests nunca usan la red ni claves reales.
