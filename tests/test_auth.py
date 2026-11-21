import pytest

from app.auth import PasswordTooShortError, hash_password, verify_password


def test_contrasena_correcta():
    stored = hash_password("una-clave-segura")
    assert verify_password("una-clave-segura", stored)


def test_contrasena_incorrecta():
    stored = hash_password("una-clave-segura")
    assert not verify_password("otra-clave-distinta", stored)


def test_contrasena_demasiado_corta():
    with pytest.raises(PasswordTooShortError, match="al menos 10 caracteres"):
        hash_password("corta123")


def test_contrasena_de_diez_caracteres_es_valida():
    assert verify_password("1234567890", hash_password("1234567890"))


def test_sal_aleatoria_y_sin_texto_en_claro():
    a = hash_password("una-clave-segura")
    b = hash_password("una-clave-segura")
    assert a != b
    assert "una-clave-segura" not in a
    assert a.startswith("scrypt$")


def test_hash_malformado_no_valida():
    assert not verify_password("una-clave-segura", "basura")
    assert not verify_password("una-clave-segura", "scrypt$x$y$z$@@$@@")
