"""Conexión a la base con un diccionario (mismo formato que `DATABASES["default"]` de Django).

    AuthSettings(database={
        "ENGINE": "postgresql",
        "NAME": "miapp",
        "USER": "app",
        "PASSWORD": os.environ["DB_PASSWORD"],
        "HOST": "localhost",
        "PORT": "5432",
        "OPTIONS": {"sslmode": "require"},
    })

Se traduce a una URL de SQLAlchemy con los valores escapados (una contraseña con `@`, `/` o `#`
funciona sin tocarla). `database_url` sigue disponible para quien prefiera la URL.
"""

from __future__ import annotations

import importlib.util
from typing import Any

from sqlalchemy.engine import URL

from djauth.errors import AuthError

# Motor (nombre corto o el de Django) -> (dialecto de SQLAlchemy, controladores en orden de preferencia)
ENGINES: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    "postgresql": ("postgresql", (("psycopg", "psycopg"), ("psycopg2", "psycopg2"), ("asyncpg", "asyncpg"))),
    "mysql": ("mysql", (("pymysql", "pymysql"), ("MySQLdb", "mysqldb"), ("mysql.connector", "mysqlconnector"))),
    "oracle": ("oracle", (("oracledb", "oracledb"),)),
    "mssql": ("mssql", (("pyodbc", "pyodbc"), ("pymssql", "pymssql"))),
    "sqlite": ("sqlite", ()),
}
ALIASES = {
    "django.db.backends.postgresql": "postgresql",
    "django.db.backends.postgresql_psycopg2": "postgresql",
    "django.contrib.gis.db.backends.postgis": "postgresql",
    "postgres": "postgresql",
    "django.db.backends.mysql": "mysql",
    "mariadb": "mysql",
    "django.db.backends.oracle": "oracle",
    "mssql": "mssql",
    "sql_server.pyodbc": "mssql",
    "django.db.backends.sqlite3": "sqlite",
    "sqlite3": "sqlite",
}
INSTALL_HINT = {
    "postgresql": 'pip install "fastapi-djauth[postgres]"  (instala psycopg)',
    "mysql": 'pip install "fastapi-djauth[mysql]"  (instala PyMySQL)',
    "oracle": "pip install oracledb",
    "mssql": "pip install pyodbc  (y el controlador ODBC de SQL Server)",
}


class DatabaseConfigError(AuthError):
    code = "database_config"
    status = 500


def _driver(engine: str, requested: str | None) -> str:
    dialect, drivers = ENGINES[engine]
    if requested:
        return f"{dialect}+{requested}"
    for module, name in drivers:
        if importlib.util.find_spec(module.split(".")[0]) is not None:
            return f"{dialect}+{name}"
    if not drivers:
        return dialect
    raise DatabaseConfigError(
        f"No hay ningún controlador de {engine} instalado.",
        hint=f"Instálelo con: {INSTALL_HINT[engine]}",
    )


def url_from_django(config: dict[str, Any]) -> URL:
    """Convierte un diccionario estilo `DATABASES["default"]` en una URL de SQLAlchemy.

    Claves: ENGINE (obligatoria), NAME, USER, PASSWORD, HOST, PORT, OPTIONS (parámetros del
    controlador, p. ej. `sslmode`) y DRIVER (opcional: forzar el controlador, p. ej. "psycopg2").
    """
    cfg = {str(k).upper(): v for k, v in config.items()}
    raw_engine = str(cfg.get("ENGINE") or "").strip()
    if not raw_engine:
        raise DatabaseConfigError(
            "Falta ENGINE en la configuración de la base de datos.",
            hint='Use p. ej. "postgresql", "mysql", "oracle", "mssql" o "sqlite".',
        )
    engine = ALIASES.get(raw_engine, raw_engine)
    if engine not in ENGINES:
        raise DatabaseConfigError(
            f"Motor de base de datos no soportado: {raw_engine}.",
            hint=f"Motores válidos: {', '.join(ENGINES)} (también se aceptan los nombres de motor de Django).",
        )
    name = str(cfg.get("NAME") or "")
    if engine == "sqlite":
        # NAME es la ruta del archivo; vacío o ":memory:" = base en memoria.
        return URL.create("sqlite", database=None if name in ("", ":memory:") else name)
    if not name:
        raise DatabaseConfigError(f"Falta NAME (nombre de la base) para {engine}.")
    port = cfg.get("PORT")
    try:
        port_number = int(port) if port not in (None, "") else None
    except (TypeError, ValueError):
        raise DatabaseConfigError(f"PORT debe ser un número (recibido: {port!r}).") from None
    options = {str(k): str(v) for k, v in (cfg.get("OPTIONS") or {}).items()}
    return URL.create(
        _driver(engine, cfg.get("DRIVER")),
        username=cfg.get("USER") or None,
        password=cfg.get("PASSWORD") or None,
        host=cfg.get("HOST") or None,
        port=port_number,
        database=name,
        query=options,
    )
