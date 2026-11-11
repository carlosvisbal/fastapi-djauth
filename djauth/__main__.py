"""Comandos de administración (como `manage.py`):

    python -m djauth --db sqlite:///auth.sqlite3 createsuperuser --username admin --email a@b.co
    python -m djauth --db … changepassword admin
    python -m djauth --db … listusers

La contraseña se pide por teclado; para scripts, use la variable DJAUTH_PASSWORD.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from djauth.core import AuthKit
from djauth.errors import AuthError, ValidationError
from djauth.settings import AuthSettings


def _ask_password() -> str:
    if env := os.environ.get("DJAUTH_PASSWORD"):
        return env
    while True:
        first = getpass.getpass("Contraseña: ")
        if first == getpass.getpass("Contraseña (otra vez): "):
            return first
        print("Las contraseñas no coinciden.", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m djauth", description="Administración de usuarios de djauth")
    parser.add_argument(
        "--db", default=os.environ.get("DJAUTH_DATABASE_URL", "sqlite:///auth.sqlite3"), help="URL de la base de datos"
    )
    parser.add_argument("--prefix", default="auth_", help="Prefijo de las tablas")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("createsuperuser", help="Crear un superusuario")
    create.add_argument("--username", required=True)
    create.add_argument("--email", default="")
    change = sub.add_parser("changepassword", help="Cambiar la contraseña de un usuario")
    change.add_argument("username")
    sub.add_parser("listusers", help="Listar usuarios")
    args = parser.parse_args(argv)

    kit = AuthKit(AuthSettings(database_url=args.db, table_prefix=args.prefix)).init()
    try:
        if args.command == "createsuperuser":
            user = kit.create_superuser(
                args.username, _ask_password(), email=args.email, reason="Creado con djauth createsuperuser."
            )
            print(f"Superusuario {user['username']} creado.")
        elif args.command == "changepassword":
            user = kit.get_by_username(args.username)
            if user is None:
                print(f"No existe el usuario {args.username}.", file=sys.stderr)
                return 1
            kit.set_password(user.id, _ask_password(), reason="Cambiada con djauth changepassword.")
            print(f"Contraseña de {user.username} cambiada; sus sesiones abiertas se cerraron.")
        elif args.command == "listusers":
            items, total = kit.list_users(limit=1000)
            for u in items:
                flags = "".join(f for f, on in (("S", u["is_superuser"]), ("A", u["is_staff"]), ("-", not u["is_active"])) if on)
                print(f"{u['id']:>5}  {u['username']:<30} {flags:<3} {', '.join(u['groups'])}")
            print(f"{total} usuarios")
    except ValidationError as exc:
        for field, messages in exc.errors.items():
            for m in messages:
                print(f"{field}: {m}", file=sys.stderr)
        return 1
    except AuthError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
