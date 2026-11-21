from datetime import UTC, datetime

import pytest

from app.auth import PasswordTooShortError
from app.services.usuarios import (
    EmailDuplicadoError,
    UsuarioError,
    check_credentials,
    create_user,
    get_user_by_email,
)

AHORA = datetime(2026, 1, 15, 10, 30, tzinfo=UTC)


def _crear(db, email="Ana@Example.com", password="una-clave-segura", **kwargs):
    return create_user(
        db, email=email, nombre="Ana", password=password, clock=lambda: AHORA, **kwargs
    )


def test_crea_usuario_normalizando_email(db):
    usuario = _crear(db, rol="admin")
    assert usuario.email == "ana@example.com"
    assert usuario.rol == "admin"
    assert usuario.activo is True
    assert usuario.creado_en == "2026-01-15T10:30:00Z"
    fila = db.execute("SELECT password_hash FROM usuarios").fetchone()
    assert "una-clave-segura" not in fila["password_hash"]


def test_rol_por_defecto_agente(db):
    assert _crear(db).rol == "agente"


def test_email_duplicado_sin_distinguir_mayusculas(db):
    _crear(db)
    with pytest.raises(EmailDuplicadoError):
        _crear(db, email="ANA@example.com")
    assert db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 1


def test_contrasena_corta_rechazada_y_no_se_crea(db):
    with pytest.raises(PasswordTooShortError):
        _crear(db, password="corta")
    assert db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0


def test_datos_invalidos(db):
    with pytest.raises(UsuarioError):
        _crear(db, email="sin-arroba")
    with pytest.raises(UsuarioError):
        _crear(db, rol="root")


def test_credenciales(db):
    _crear(db)
    assert check_credentials(db, "ana@example.com", "una-clave-segura") is not None
    assert check_credentials(db, "ANA@example.com", "una-clave-segura") is not None
    assert check_credentials(db, "ana@example.com", "incorrecta-xx") is None
    assert check_credentials(db, "nadie@example.com", "una-clave-segura") is None


def test_usuario_inactivo_no_autentica(db):
    _crear(db)
    db.execute("UPDATE usuarios SET activo = 0")
    db.commit()
    assert check_credentials(db, "ana@example.com", "una-clave-segura") is None


def test_get_user_by_email(db):
    _crear(db)
    assert get_user_by_email(db, " ANA@example.com ").nombre == "Ana"
    assert get_user_by_email(db, "otro@example.com") is None
