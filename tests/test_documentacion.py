import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CI = RAIZ / ".github" / "workflows" / "ci.yml"
README = RAIZ / "README.md"


def test_ci_existe_y_se_dispara_en_push_y_pull_request():
    texto = CI.read_text(encoding="utf-8")
    assert re.search(r"^on:\s*$", texto, re.MULTILINE)
    assert re.search(r"^  push:", texto, re.MULTILINE)
    assert re.search(r"^  pull_request:", texto, re.MULTILINE)


def test_ci_usa_python_312():
    assert re.search(r'python-version:\s*"?3\.12"?', CI.read_text(encoding="utf-8"))


def test_ci_ejecuta_ruff_y_pytest():
    texto = CI.read_text(encoding="utf-8")
    assert re.search(r"run:\s*ruff check \.", texto)
    assert re.search(r"run:\s*pytest", texto)
    assert "requirements.txt" in texto


def test_ci_no_necesita_secretos():
    texto = CI.read_text(encoding="utf-8")
    assert "secrets." not in texto
    assert "OPENROUTER_API_KEY" not in texto


def test_readme_incluye_insignia_del_workflow():
    texto = README.read_text(encoding="utf-8")
    assert re.search(
        r"!\[[^\]]*\]\(https://github\.com/[^)]+/actions/workflows/ci\.yml/badge\.svg\)", texto
    )


def test_readme_describe_producto_y_funcionalidades():
    texto = README.read_text(encoding="utf-8")
    assert "# TriageBot Pro" in texto
    assert "## Funcionalidades" in texto
    for palabra in ("IA", "SLA", "Panel", "Auditoría", "Importación"):
        assert palabra in texto


def test_readme_demo_en_tres_comandos():
    texto = README.read_text(encoding="utf-8")
    seccion = texto.split("## Demo en tres comandos", 1)[1].split("\n## ", 1)[0]
    bloque = re.search(r"```bash\n(.*?)```", seccion, re.DOTALL)
    assert bloque is not None
    comandos = [linea for linea in bloque.group(1).splitlines() if linea.strip()]
    assert len(comandos) == 3
    assert "pip install -r requirements.txt" in comandos[0]
    assert "app.cli demo" in comandos[1]
    assert "uvicorn app.main:app" in comandos[2]


def test_readme_documenta_la_estructura_real_del_codigo():
    texto = README.read_text(encoding="utf-8")
    assert "## Estructura del código" in texto
    for ruta in (
        "main.py",
        "config.py",
        "db.py",
        "auth.py",
        "cli.py",
        "routers/",
        "services/",
        "templates/",
        "static/",
        "tests/",
        "fixtures/",
    ):
        assert ruta in texto
    for carpeta in ("app/routers", "app/services", "app/templates", "app/static", "tests/fixtures"):
        assert (RAIZ / carpeta).is_dir()
