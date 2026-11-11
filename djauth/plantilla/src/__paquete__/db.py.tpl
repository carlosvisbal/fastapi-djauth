"""Base de datos de la aplicación (SQLAlchemy 2). Los cambios de tablas se hacen con Alembic (migrations/)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import Request
from sqlalchemy import Engine, create_engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Base de los modelos de la aplicación. Las tablas de usuarios (auth_*) las gestiona djauth."""


def build_engine(url: str, **options: Any) -> Engine:
    kwargs: dict[str, Any] = {"pool_pre_ping": True, **options}
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False}
        if parsed.database and parsed.database != ":memory:":
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)  # p. ej. ./data/
    return create_engine(parsed, **kwargs)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def get_session(request: Request) -> Iterator[Session]:
    """Una sesión por petición: se confirma si todo sale bien y se deshace si hay un error."""
    factory: sessionmaker[Session] = request.app.state.session_factory
    with factory() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
