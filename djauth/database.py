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
    "postgresql": ("postgresql", (("psycopg", "psycopg"), ("psycopg2", "psycopg2"))),
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
    "oracle": 'pip install "fastapi-djauth[oracle]"  (instala oracledb)',
    "mssql": 'pip install "fastapi-djauth[mssql]"  (instala pymssql; o pyodbc con el controlador ODBC de Microsoft)',
}


# Controladores asíncronos: el módulo usa SQLAlchemy síncrono (FastAPI lo ejecuta en su pool de hilos).
ASYNC_DRIVERS = {"asyncpg", "aiomysql", "asyncmy", "aiosqlite", "aioodbc", "psycopg_async"}
SYNC_HINT = {"asyncpg": "psycopg", "aiomysql": "pymysql", "asyncmy": "pymysql", "aiosqlite": "", "aioodbc": "pyodbc"}


class DatabaseConfigError(AuthError):
    code = "database_config"
    status = 500


def check_sync_driver(url: URL) -> URL:
    """Rechaza con un error claro los controladores asíncronos (fallarían más tarde y sin explicación)."""
    driver = url.get_driver_name()
    if driver in ASYNC_DRIVERS:
        sync = SYNC_HINT.get(driver, "")
        target = f"{url.get_backend_name()}+{sync}" if sync else url.get_backend_name()
        raise DatabaseConfigError(
            f"El controlador {driver} es asíncrono y djauth necesita uno síncrono.",
            hint=f"Use {target}://… (su aplicación puede seguir usando {driver} para sus propias consultas).",
        )
    return url


def _driver(engine: str, requested: str | None) -> str:
    dialect, drivers = ENGINES[engine]
    if requested:
        return f"{dialect}+{requested}"
    for module, name in drivers:
        try:
            found = importlib.util.find_spec(module) is not None
        except ModuleNotFoundError:  # "mysql.connector" sin el paquete "mysql"
            found = False
        if found:
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
    oracle_sid = engine == "oracle" and any(str(k).lower() == "sid" for k in (cfg.get("OPTIONS") or {}))
    if not name and not oracle_sid:
        what = "nombre del servicio" if engine == "oracle" else "nombre de la base"
        raise DatabaseConfigError(f"Falta NAME ({what}) para {engine}.")
    port = cfg.get("PORT")
    try:
        port_number = int(port) if port not in (None, "") else None
    except (TypeError, ValueError):
        raise DatabaseConfigError(f"PORT debe ser un número (recibido: {port!r}).") from None
    options = {str(k): str(v) for k, v in (cfg.get("OPTIONS") or {}).items()}
    database: str | None = name
    if engine == "oracle":
        # En Oracle, NAME es el nombre del servicio (FREEPDB1, ORCLPDB1…), lo habitual hoy. Para una
        # base antigua identificada por SID: OPTIONS={"sid": "ORCL"} (NAME se ignora).
        sid = options.pop("sid", None) or options.pop("SID", None)
        if sid:
            database = sid
        else:
            database = None
            options.setdefault("service_name", name)
    return URL.create(
        _driver(engine, cfg.get("DRIVER")),
        username=cfg.get("USER") or None,
        password=cfg.get("PASSWORD") or None,
        host=cfg.get("HOST") or None,
        port=port_number,
        database=database,
        query=options,
    )
