"""Control de acceso por rol: dependencia reutilizable `require_role`."""

from collections.abc import Callable

from fastapi import HTTPException, Request

from app.services.usuarios import ROLES, Usuario

MENSAJE_PROHIBIDO = "No tienes permisos para acceder a esta sección."


def require_role(*roles: str) -> Callable[[Request], Usuario]:
    """Crea una dependencia que deja pasar solo a los usuarios con alguno de `roles`.

    Devuelve el usuario autenticado (cargado y verificado como activo por el middleware de
    sesión). Responde 403 si su rol no está permitido y 401 si no hay usuario en la petición.
    """
    if not roles:
        raise ValueError("require_role necesita al menos un rol.")
    desconocidos = set(roles) - set(ROLES)
    if desconocidos:
        raise ValueError(f"Rol no válido: {', '.join(sorted(desconocidos))}.")

    def dependencia(request: Request) -> Usuario:
        usuario: Usuario | None = getattr(request.state, "usuario", None)
        if usuario is None:
            raise HTTPException(status_code=401, detail="No autenticado")
        if usuario.rol not in roles:
            raise HTTPException(status_code=403, detail=MENSAJE_PROHIBIDO)
        return usuario

    return dependencia
