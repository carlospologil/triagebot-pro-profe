"""Comandos de administración: `python -m app.cli crear-admin --email X --nombre Y`."""

import argparse
import getpass
import sys
from collections.abc import Sequence

from app.auth import PasswordTooShortError
from app.config import ConfigError, load_settings
from app.db import connect, migrate
from app.services.usuarios import UsuarioError, create_user


def _crear_admin(args: argparse.Namespace) -> int:
    password = getpass.getpass("Contraseña: ")
    if getpass.getpass("Repite la contraseña: ") != password:
        print("Error: las contraseñas no coinciden.", file=sys.stderr)
        return 1
    settings = load_settings()
    conn = connect(settings.database_path)
    try:
        migrate(conn)
        usuario = create_user(
            conn, email=args.email, nombre=args.nombre, password=password, rol="admin"
        )
    except (UsuarioError, PasswordTooShortError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(f"Administrador creado: {usuario.email} (id {usuario.id}).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description="Administración de TriageBot Pro")
    subparsers = parser.add_subparsers(dest="comando", required=True)
    admin = subparsers.add_parser("crear-admin", help="Crea un usuario administrador")
    admin.add_argument("--email", required=True)
    admin.add_argument("--nombre", required=True)
    admin.set_defaults(func=_crear_admin)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
