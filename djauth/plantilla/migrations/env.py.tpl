"""Entorno de Alembic: usa la URL de la configuración y solo los modelos de la aplicación."""

from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import pool

import __paquete__.models  # noqa: F401  (registra los modelos en Base.metadata)
from __paquete__.core.config import get_settings
from __paquete__.db import Base, build_engine

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
DATABASE_URL = get_settings().database_url
target_metadata = Base.metadata


def include_object(obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any) -> bool:
    # Las tablas de usuarios (auth_*) las crea y mantiene djauth: Alembic no debe tocarlas.
    return not (type_ == "table" and reflected and compare_to is None)


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = build_engine(DATABASE_URL, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            render_as_batch=connection.dialect.name == "sqlite",  # ALTER TABLE en SQLite
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
