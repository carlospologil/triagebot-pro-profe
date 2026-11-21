"""Almacenamiento seguro de contraseñas con hashlib.scrypt."""

import base64
import hashlib
import hmac
import secrets

MIN_PASSWORD_LENGTH = 10
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LENGTH = 32
SALT_LENGTH = 16
_SCHEME = "scrypt"


class PasswordTooShortError(ValueError):
    """La contraseña no alcanza la longitud mínima."""


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordTooShortError(
            f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres."
        )


def _derive(password: str, salt: bytes, n: int, r: int, p: int, length: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=length)


def hash_password(password: str) -> str:
    """Valida la contraseña y devuelve `scrypt$n$r$p$sal$hash` (sal aleatoria por llamada)."""
    validate_password(password)
    salt = secrets.token_bytes(SALT_LENGTH)
    digest = _derive(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P, KEY_LENGTH)
    return "$".join(
        [
            _SCHEME,
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored_hash.split("$")
        if scheme != _SCHEME:
            return False
        salt = base64.b64decode(salt_b64, validate=True)
        expected = base64.b64decode(digest_b64, validate=True)
        actual = _derive(password, salt, int(n), int(r), int(p), len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)
