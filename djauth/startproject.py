"""`djauth startproject`: crea un proyecto FastAPI nuevo, con arquitectura por capas y djauth integrado.

    djauth startproject inventario
    djauth startproject inventario --db postgresql --versiones ultimas --titulo "Inventario general"

Dos modos de versiones:

- `probadas` (por defecto): fija las versiones exactas con las que se probó esta versión de djauth.
  Es lo reproducible: el proyecto funciona igual hoy y dentro de un año.
- `ultimas`: pide solo un mínimo compatible, y `uv` instala lo más reciente que exista al crear el
  proyecto. Luego `uv.lock` las fija igualmente.

Solo crea proyectos nuevos: nunca escribe sobre una carpeta que ya tenga archivos. El único programa
externo que ejecuta es `uv lock`, con argumentos fijos y sin shell.
"""

from __future__ import annotations

import argparse
import keyword
import os
import re
import secrets
import shutil
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from pathlib import Path

from djauth import __version__

TEMPLATE_DIR = Path(__file__).parent / "plantilla"
PYTHON_IMAGE = "3.14"  # imagen base del Dockerfile
UV_IMAGE = "0.11.28"
PLACEHOLDER = "CAMBIAR"  # en .env.example, en lugar de la contraseña real de la base

# Versiones con las que se probó la plantilla en esta versión de djauth (modo "probadas").
TESTED: dict[str, str] = {
    "fastapi[standard]": "0.162.4",
    "sqlalchemy": "2.1.8",
    "pydantic-settings": "2.16.2",
    "alembic": "1.20.1",
    "psycopg[binary]": "3.3.8",
    "pymysql[rsa]": "1.2.4",
    "pytest": "9.2.0",
    "ruff": "0.17.4",
    "mypy": "2.4.1",
}
# Mínimos compatibles (modo "ultimas": uv elige la versión más reciente que los cumpla).
MINIMUM: dict[str, str] = {
    "fastapi[standard]": "0.115",
    "sqlalchemy": "2.0.24",
    "pydantic-settings": "2.6",
    "alembic": "1.14",
    "psycopg[binary]": "3.2",
    "pymysql[rsa]": "1.1",
    "pytest": "8.3",
    "ruff": "0.8",
    "mypy": "1.13",
}

DATABASES: dict[str, dict[str, str]] = {
    "sqlite": {"driver": "", "url": "sqlite:///./data/app.sqlite3"},
    "postgresql": {"driver": "psycopg[binary]", "url": "postgresql+psycopg://app:{password}@localhost:5432/app"},
    "mysql": {"driver": "pymysql[rsa]", "url": "mysql+pymysql://app:{password}@localhost:3306/app?charset=utf8mb4"},
}
# Nombres que romperían imports si se usaran como paquete del proyecto.
RESERVED = {"djauth", "fastapi", "sqlalchemy", "pydantic", "alembic", "test", "tests", "src", "app", "main", "api"}
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,49}$")


class StartProjectError(Exception):
    """Error al crear el proyecto, con un mensaje para la persona."""


@dataclass(frozen=True)
class Result:
    path: Path
    admin_password: str
    locked: bool


def _check_name(name: str) -> None:
    if not NAME_RE.match(name):
        raise StartProjectError(
            f"Nombre no válido: {name!r}. Use minúsculas, números y guion bajo, empezando por una letra "
            "(p. ej. inventario o control_calidad)."
        )
    if keyword.iskeyword(name) or name in RESERVED:
        raise StartProjectError(f"{name!r} está reservado (chocaría con Python o con una librería). Elija otro nombre.")


def _requirement(package: str, mode: str) -> str:
    return f'"{package}=={TESTED[package]}"' if mode == "probadas" else f'"{package}>={MINIMUM[package]}"'


def _compose(db: str, name: str) -> str:
    app = """services:
  app:
    build: .
    ports: ["${APP_PORT:-8000}:8000"]  # otro puerto: APP_PORT=8080 docker compose up
    env_file: .env
    environment:
      APP_ENVIRONMENT: produccion
"""
    if db == "sqlite":
        return (
            app
            + f"""      APP_DATABASE_URL: sqlite:////app/data/app.sqlite3
    volumes: ["{name}-data:/app/data"]
    restart: unless-stopped

volumes:
  {name}-data:
"""
        )
    if db == "postgresql":
        return (
            app
            + f"""      APP_DATABASE_URL: postgresql+psycopg://app:${{DB_PASSWORD}}@db:5432/app
    depends_on:
      db: {{condition: service_healthy}}
    restart: unless-stopped

  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: ${{DB_PASSWORD}}
      POSTGRES_DB: app
    volumes: ["{name}-db:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app"]
      interval: 5s
      retries: 20
    restart: unless-stopped

volumes:
  {name}-db:
"""
        )
    return (
        app
        + f"""      APP_DATABASE_URL: mysql+pymysql://app:${{DB_PASSWORD}}@db:3306/app?charset=utf8mb4
    depends_on:
      db: {{condition: service_healthy}}
    restart: unless-stopped

  db:
    image: mysql:8.4
    environment:
      MYSQL_RANDOM_ROOT_PASSWORD: "yes"
      MYSQL_USER: app
      MYSQL_PASSWORD: ${{DB_PASSWORD}}
      MYSQL_DATABASE: app
    volumes: ["{name}-db:/var/lib/mysql"]
    healthcheck:
      test: ["CMD-SHELL", "mysqladmin ping -uapp -p$${{MYSQL_PASSWORD}} --silent"]
      interval: 5s
      retries: 30
    restart: unless-stopped

volumes:
  {name}-db:
"""
    )


def create_project(
    name: str,
    target: Path | None = None,
    *,
    db: str = "sqlite",
    versions: str = "probadas",
    title: str | None = None,
    lock: bool = True,
    djauth_source: Path | None = None,
) -> Result:
    """Crea el proyecto en `target` (por defecto, ./<name>). Devuelve la ruta y la contraseña del admin."""
    _check_name(name)
    if db not in DATABASES:
        raise StartProjectError(f"Base de datos no soportada en la plantilla: {db}. Use: {', '.join(DATABASES)}.")
    if versions not in ("probadas", "ultimas"):
        raise StartProjectError('--versiones debe ser "probadas" o "ultimas".')
    target = (target or Path.cwd() / name).resolve()
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise StartProjectError(f"{target} ya existe y no está vacía. djauth startproject solo crea proyectos nuevos.")

    db_password = secrets.token_urlsafe(18)
    admin_password = secrets.token_urlsafe(14)
    database_url = DATABASES[db]["url"].format(password=PLACEHOLDER)
    djauth_req = f'"fastapi-djauth=={__version__}"' if versions == "probadas" else f'"fastapi-djauth>={__version__}"'
    deps = [djauth_req, *(_requirement(p, versions) for p in ("fastapi[standard]", "sqlalchemy", "pydantic-settings", "alembic"))]
    if DATABASES[db]["driver"]:
        deps.append(_requirement(DATABASES[db]["driver"], versions))
    dev_deps = [_requirement(p, versions) for p in ("pytest", "ruff", "mypy")]
    replacements = {
        "__paquete__": name,
        "__nombre__": (title or name.replace("_", " ").capitalize()).replace('"', "'"),
        "__dependencias__": "\n".join(f"    {d}," for d in deps),
        "__dependencias_dev__": "\n".join(f"    {d}," for d in dev_deps),
        "__database_url__": database_url,
        "__env_db__": "" if db == "sqlite" else "# Contraseña de la base de datos (docker compose)\nDB_PASSWORD=",
        "__python__": PYTHON_IMAGE,
        "__uv__": UV_IMAGE,
    }

    target.mkdir(parents=True, exist_ok=True)
    for source in sorted(TEMPLATE_DIR.rglob("*.tpl")):
        relative = source.relative_to(TEMPLATE_DIR).as_posix().removesuffix(".tpl").replace("__paquete__", name)
        text = source.read_text(encoding="utf-8")
        for token, value in replacements.items():
            text = text.replace(token, value)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
    (target / "compose.yaml").write_text(_compose(db, name.replace("_", "-")), encoding="utf-8")

    # .env con secretos propios del proyecto (solo lo puede leer su dueño).
    env = (target / ".env.example").read_text(encoding="utf-8")
    env = env.replace("APP_SECRET_KEY=\n", f"APP_SECRET_KEY={secrets.token_urlsafe(48)}\n")
    env = env.replace("APP_ADMIN_PASSWORD=\n", f"APP_ADMIN_PASSWORD={admin_password}\n")
    env = env.replace("DB_PASSWORD=", f"DB_PASSWORD={db_password}")
    env = env.replace(database_url, DATABASES[db]["url"].format(password=db_password))
    env_path = target / ".env"
    env_path.write_text(env, encoding="utf-8")
    env_path.chmod(0o600)

    if djauth_source is not None:  # desarrollo de djauth: probar la plantilla con el código local
        with (target / "pyproject.toml").open("a", encoding="utf-8") as fh:
            fh.write(f'\n[tool.uv.sources]\nfastapi-djauth = {{ path = "{djauth_source.resolve().as_posix()}" }}\n')

    locked = False
    uv = shutil.which("uv")
    if lock and uv:
        done = subprocess.run([uv, "lock", "--quiet"], cwd=target, check=False)  # nosec B603
        locked = done.returncode == 0
    return Result(path=target, admin_password=admin_password, locked=locked)


def main(args: argparse.Namespace) -> int:
    """Ejecuta el comando con los argumentos de argparse (ver `djauth.__main__`)."""
    source = os.environ.get("DJAUTH_PLANTILLA_FUENTE")
    name: str = args.name
    try:
        result = create_project(
            name,
            Path(args.directory) if args.directory else None,
            db=args.db_engine,
            versions=args.versions,
            title=args.title,
            lock=not args.no_lock,
            djauth_source=Path(source) if source else None,
        )
    except StartProjectError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    try:
        shown = result.path.relative_to(Path.cwd())
    except ValueError:
        shown = result.path
    print(f"Proyecto creado en {shown}\n")
    print(f"  Superusuario: admin  ·  contraseña: {result.admin_password}")
    print("  (está en .env; cámbiela tras el primer inicio de sesión)\n")
    print("Siguientes pasos:")
    print(f"  cd {shown}")
    print("  uv sync" + ("" if result.locked else "            # crea uv.lock e instala las dependencias"))
    print("  uv run alembic upgrade head")
    print(f"  uv run uvicorn {name}.main:create_app --factory --reload")
    print("\nLuego abra http://127.0.0.1:8000/auth/login y http://127.0.0.1:8000/docs")
    return 0
