from types import SimpleNamespace

import pytest

from app.flash import CLAVE_FLASH, flash, recoger_flash


def peticion(session=None):
    sesion = {} if session is None else session
    return SimpleNamespace(session=sesion, scope={"session": sesion})


def test_flash_se_lee_una_sola_vez():
    request = peticion()
    flash(request, "Hecho")
    flash(request, "Fallo", "error")
    assert recoger_flash(request) == [("ok", "Hecho"), ("error", "Fallo")]
    assert recoger_flash(request) == []
    assert CLAVE_FLASH not in request.session


def test_flash_rechaza_tipos_desconocidos():
    with pytest.raises(ValueError):
        flash(peticion(), "x", "peligro")


def test_recoger_sin_sesion_devuelve_vacio():
    assert recoger_flash(SimpleNamespace(scope={})) == []


def test_recoger_ignora_datos_corruptos():
    request = peticion({CLAVE_FLASH: "basura"})
    assert recoger_flash(request) == []
    request = peticion({CLAVE_FLASH: [["ok", "bien"], ["solo-uno"], 3]})
    assert recoger_flash(request) == [("ok", "bien")]
