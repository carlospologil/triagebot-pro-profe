"""Comandos de administración: `python -m app.cli crear-admin --email X --nombre Y`."""

import argparse
import getpass
import sys
from collections.abc import Sequence
from pathlib import Path

from app.auth import PasswordTooShortError
from app.clock import system_clock
from app.config import ConfigError, load_settings
from app.db import connect, migrate
from app.services import demo, importacion
from app.services.clasificador import crear_cliente
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


def _importar(args: argparse.Namespace) -> int:
    settings = load_settings()
    try:
        filas = importacion.leer_filas(Path(args.ruta))
    except importacion.ImportacionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    clasificar = not args.sin_clasificar
    cliente = None
    if clasificar:
        if settings.openrouter_api_key:
            cliente = crear_cliente(settings.openrouter_api_key)
        else:
            print(
                "Aviso: OPENROUTER_API_KEY no está definida; los tickets quedarán sin clasificar.",
                file=sys.stderr,
            )
    conn = connect(settings.database_path)
    try:
        migrate(conn)
        resultado = importacion.importar_tickets(
            conn, filas, cliente, system_clock, clasificar=clasificar
        )
    finally:
        conn.close()
    for motivo in resultado.saltados:
        print(f"Saltada: {motivo}", file=sys.stderr)
    if clasificar and resultado.sin_clasificar:
        print(
            f"Aviso: {resultado.sin_clasificar} ticket(s) no se pudieron clasificar "
            "y quedan como sin_clasificar.",
            file=sys.stderr,
        )
    print(f"Importados: {resultado.importados}. Saltados: {len(resultado.saltados)}.")
    return 0


def _demo(args: argparse.Namespace) -> int:
    settings = load_settings()
    conn = connect(settings.database_path)
    try:
        migrate(conn)
        credenciales = demo.crear_datos_demo(conn, system_clock)
    except UsuarioError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(f"Datos de demostración creados: 1 admin, 3 agentes y {demo.TOTAL_TICKETS} tickets.")
    print("Credenciales:")
    for email, rol, password in credenciales:
        print(f"  {rol:<7} {email}  {password}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description="Administración de TriageBot Pro")
    subparsers = parser.add_subparsers(dest="comando", required=True)
    admin = subparsers.add_parser("crear-admin", help="Crea un usuario administrador")
    admin.add_argument("--email", required=True)
    admin.add_argument("--nombre", required=True)
    admin.set_defaults(func=_crear_admin)
    importar = subparsers.add_parser(
        "importar", help="Importa tickets desde un CSV (columna texto) o un JSON (lista de objetos)"
    )
    importar.add_argument("ruta", metavar="RUTA", help="Fichero .csv o .json")
    importar.add_argument(
        "--sin-clasificar",
        action="store_true",
        help="No llama a la IA: los tickets quedan con categoría sin_clasificar",
    )
    importar.set_defaults(func=_importar)
    subparsers.add_parser(
        "demo", help="Crea datos de demostración (usuarios y tickets) sin llamar a la IA"
    ).set_defaults(func=_demo)
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
