from concurrent.futures import ThreadPoolExecutor

from app.db import connect
from app.services import autenticacion
from app.services.autenticacion import (
    MAX_INTENTOS_FALLIDOS,
    authenticate,
    get_active_user,
)
from app.services.usuarios import create_user

PASSWORD = "una-clave-segura"


def _fila(db):
    return db.execute("SELECT intentos_fallidos, bloqueado_hasta FROM usuarios").fetchone()


def test_credenciales_correctas_devuelven_el_usuario(db, reloj):
    creado = create_user(db, email="ana@example.com", nombre="Ana", password=PASSWORD)
    assert authenticate(db, "ANA@example.com", PASSWORD, reloj) == creado


def test_email_inexistente_o_clave_erronea_devuelven_none(db, reloj):
    create_user(db, email="ana@example.com", nombre="Ana", password=PASSWORD)
    assert authenticate(db, "otro@example.com", PASSWORD, reloj) is None
    assert authenticate(db, "ana@example.com", "incorrecta-123", reloj) is None


def test_cuenta_fallos_y_bloquea_al_llegar_al_maximo(db, reloj):
    create_user(db, email="ana@example.com", nombre="Ana", password=PASSWORD)
    for esperados in range(1, MAX_INTENTOS_FALLIDOS):
        authenticate(db, "ana@example.com", "incorrecta-123", reloj)
        assert _fila(db)["intentos_fallidos"] == esperados
    authenticate(db, "ana@example.com", "incorrecta-123", reloj)
    assert _fila(db)["bloqueado_hasta"] == "2026-03-02T09:15:00Z"
    assert authenticate(db, "ana@example.com", PASSWORD, reloj) is None


def test_acierto_limpia_contador_y_bloqueo_caducado(db, reloj):
    create_user(db, email="ana@example.com", nombre="Ana", password=PASSWORD)
    for _ in range(MAX_INTENTOS_FALLIDOS):
        authenticate(db, "ana@example.com", "incorrecta-123", reloj)
    reloj.avanzar(minutes=15)
    assert authenticate(db, "ana@example.com", PASSWORD, reloj) is not None
    assert tuple(_fila(db)) == (0, None)


def test_get_active_user_ignora_inactivos(db):
    creado = create_user(db, email="ana@example.com", nombre="Ana", password=PASSWORD)
    assert get_active_user(db, creado.id) == creado
    db.execute("UPDATE usuarios SET activo = 0")
    db.commit()
    assert get_active_user(db, creado.id) is None
    assert get_active_user(db, 999) is None


def test_intentos_paralelos_no_superan_el_maximo_de_verificaciones(
    db, settings, reloj, monkeypatch
):
    create_user(db, email="ana@example.com", nombre="Ana", password=PASSWORD)
    hash_real = db.execute("SELECT password_hash FROM usuarios").fetchone()[0]
    verificaciones = []
    original = autenticacion.verify_password

    def contando(password, stored_hash):
        if stored_hash == hash_real:
            verificaciones.append(password)
        return original(password, stored_hash)

    monkeypatch.setattr(autenticacion, "verify_password", contando)

    def intento(_):
        conn = connect(settings.database_path)
        try:
            return authenticate(conn, "ana@example.com", "incorrecta-123", reloj)
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=12) as pool:
        resultados = list(pool.map(intento, range(12)))

    assert resultados == [None] * 12
    assert len(verificaciones) == MAX_INTENTOS_FALLIDOS
    assert _fila(db)["bloqueado_hasta"] == "2026-03-02T09:15:00Z"
    assert authenticate(db, "ana@example.com", PASSWORD, reloj) is None
