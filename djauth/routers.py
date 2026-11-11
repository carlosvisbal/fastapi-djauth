"""Varias bases de datos y routers: el equivalente de `DATABASES` y `DATABASE_ROUTERS` de Django.

    AuthSettings(
        databases={
            "default": {"ENGINE": "postgresql", "NAME": "miapp", "HOST": "primaria", ...},
            "replica": {"ENGINE": "postgresql", "NAME": "miapp", "HOST": "replica", "READ_ONLY": True},
        },
        database_routers=["miapp.routers.PrimaryReplicaRouter"],
    )

Un router es una clase con cualquiera de estos métodos, que devuelven `None` cuando no tienen opinión
(y entonces decide el siguiente router, como en Django):

- `db_for_read(model, **hints)` → alias de la base para leer.
- `db_for_write(model, **hints)` → alias de la base para escribir.
- `allow_relation(obj1, obj2, **hints)` → `True`/`False`: ¿se pueden relacionar?
- `allow_migrate(db, app_label, model_name=None, **hints)` → ¿se crean las tablas de ese modelo en `db`?

Los modelos tienen `model._meta.app_label`, `model._meta.model_name` y `model._meta.db_table`, como en
Django, así que un router escrito para Django funciona igual.

Seguros (los de Django, más los que en Django quedan a cargo del desarrollador):

1. Una base con `"READ_ONLY": True` nunca recibe escrituras ni tablas nuevas, aunque un router lo pida.
2. Un router que devuelve un alias inexistente produce un error con los alias válidos.
3. Relaciones entre bases: `allow_relation` se comprueba antes de guardar, y las claves foráneas entre
   tablas que se escriben en bases distintas se rechazan al arrancar.
4. Leer, modificar y escribir ocurre en la misma base: una sesión de escritura lee de la base de escritura,
   así que nunca se modifica un dato leído de una réplica atrasada.
5. Las tablas solo se crean en las bases que `allow_migrate` permite, y nunca en las de solo lectura.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, MetaData, Table, create_engine, event, make_url
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql.util import find_tables

from djauth.backends import load_backend
from djauth.database import DatabaseConfigError, check_sync_driver, url_from_django

logger = logging.getLogger("djauth")

DEFAULT_DB_ALIAS = "default"
ALIAS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,49}$")
# Claves propias de cada alias, además de las de conexión (ENGINE, NAME, USER…).
ALIAS_KEYS = {"CONN_MAX_AGE", "READ_ONLY"}


@dataclass(frozen=True)
class ModelMeta:
    """Lo que un router necesita saber de un modelo (como `Model._meta` en Django)."""

    app_label: str
    model_name: str
    db_table: str


def model_meta(model: Any) -> ModelMeta:
    """`_meta` de un modelo: el que declara (modelos de djauth) o uno deducido.

    En sus modelos puede fijar `__app_label__ = "ventas"`. Si no, se toma del módulo: el paquete que
    contiene `models` (`ventas.models.pedido` → `ventas`) o el primer nombre del módulo.
    """
    cls = model if isinstance(model, type) else type(model)
    meta = cls.__dict__.get("_meta")
    if isinstance(meta, ModelMeta):
        return meta
    table = getattr(cls, "__tablename__", None) or getattr(getattr(cls, "__table__", None), "name", "") or ""
    label = getattr(cls, "__app_label__", None)
    if not label:
        parts = cls.__module__.split(".")
        label = parts[parts.index("models") - 1] if "models" in parts[1:] else parts[0]
    result = ModelMeta(app_label=str(label), model_name=cls.__name__.lower(), db_table=str(table))
    with suppress(AttributeError, TypeError):
        setattr(cls, "_meta", result)  # noqa: B010  (se calcula una vez por clase)
    return result


class BaseRouter:
    """Base opcional para escribir un router: cada método devuelve None (sin opinión)."""

    def db_for_read(self, model: type, **hints: Any) -> str | None:
        return None

    def db_for_write(self, model: type, **hints: Any) -> str | None:
        return None

    def allow_relation(self, obj1: Any, obj2: Any, **hints: Any) -> bool | None:
        return None

    def allow_migrate(self, db: str, app_label: str, model_name: str | None = None, **hints: Any) -> bool | None:
        return None


class ConnectionRouter:
    """Consulta los routers en orden, como `django.db.router`."""

    def __init__(self, routers: Iterable[Any], aliases: Iterable[str]) -> None:
        self.routers = [load_backend(r)[1] for r in routers]
        self.aliases = tuple(aliases)

    def _check(self, alias: Any, router: Any, method: str) -> str:
        if alias not in self.aliases:
            raise DatabaseConfigError(
                f"El router {type(router).__name__}.{method} devolvió la base {alias!r}, que no está configurada.",
                hint=f"Bases configuradas en `databases`: {', '.join(self.aliases)}.",
            )
        return str(alias)

    def _route(self, method: str, model: Any, hints: dict[str, Any]) -> str:
        cls = model if isinstance(model, type) else type(model)
        model_meta(cls)  # garantiza model._meta para los routers
        for router in self.routers:
            chosen = getattr(router, method, None)
            if chosen is None:
                continue
            alias = chosen(cls, **hints)
            if alias is not None:
                return self._check(alias, router, method)
        return DEFAULT_DB_ALIAS

    def db_for_read(self, model: Any, **hints: Any) -> str:
        return self._route("db_for_read", model, hints)

    def db_for_write(self, model: Any, **hints: Any) -> str:
        return self._route("db_for_write", model, hints)

    def allow_relation(self, obj1: Any, obj2: Any, **hints: Any) -> bool:
        for router in self.routers:
            method = getattr(router, "allow_relation", None)
            if method is None:
                continue
            allowed = method(obj1, obj2, **hints)
            if allowed is not None:
                return bool(allowed)
        # Por defecto (igual que Django): solo si los dos están en la misma base.
        return self.db_for_write(obj1) == self.db_for_write(obj2)

    def migrate_opinion(self, db: str, app_label: str, **hints: Any) -> bool | None:
        """Lo que dice el primer router con opinión, o None si ninguno la tiene."""
        for router in self.routers:
            method = getattr(router, "allow_migrate", None)
            if method is None:
                continue
            allowed = method(db, app_label, **hints)
            if allowed is not None:
                return bool(allowed)
        return None

    def allow_migrate(self, db: str, app_label: str, **hints: Any) -> bool:
        opinion = self.migrate_opinion(db, app_label, **hints)
        return True if opinion is None else opinion

    def allow_migrate_model(self, db: str, model: Any) -> bool | None:
        meta = model_meta(model)
        return self.migrate_opinion(db, meta.app_label, model_name=meta.model_name, model=model)


def _normalize(config: Any, alias: str, conn_max_age: int) -> tuple[URL, dict[str, Any]]:
    if isinstance(config, str | URL):
        return check_sync_driver(make_url(config)), {"CONN_MAX_AGE": conn_max_age, "READ_ONLY": False}
    if not isinstance(config, dict):
        raise DatabaseConfigError(f"La base {alias!r} debe ser un diccionario (ENGINE, NAME…) o una URL.")
    upper = {str(k).upper(): v for k, v in config.items()}
    extra = {
        "CONN_MAX_AGE": int(upper.get("CONN_MAX_AGE", conn_max_age) or 0),
        "READ_ONLY": bool(upper.get("READ_ONLY", False)),
    }
    connection = {k: v for k, v in upper.items() if k not in ALIAS_KEYS}
    return check_sync_driver(url_from_django(connection)), extra


class Databases:
    """Las conexiones de cada alias y el router (como `django.db.connections` + `router`).

    Sirve también para los modelos de su aplicación: `databases.session()` da una sesión de
    SQLAlchemy que envía cada consulta a la base que decide el router.
    """

    def __init__(self, config: dict[str, Any], routers: Iterable[Any] = (), *, conn_max_age: int = 1800) -> None:
        if DEFAULT_DB_ALIAS not in config:
            raise DatabaseConfigError(
                'Falta la base "default" en `databases`.',
                hint='Como en Django, `databases` debe tener un alias "default" (los demás son opcionales).',
            )
        for alias in config:
            if not ALIAS_RE.match(str(alias)):
                raise DatabaseConfigError(f"Alias de base no válido: {alias!r} (use letras, números, _ o -).")
        self.urls: dict[str, URL] = {}
        self.options: dict[str, dict[str, Any]] = {}
        for alias, value in config.items():
            self.urls[alias], self.options[alias] = _normalize(value, alias, conn_max_age)
        self.router = ConnectionRouter(routers, self.urls)
        self._engines: dict[str, Engine] = {}
        self._tables: dict[Table, type] = {}

    # ------------------------------------------------------------------ conexiones
    @property
    def aliases(self) -> tuple[str, ...]:
        return tuple(self.urls)

    def is_read_only(self, alias: str) -> bool:
        return bool(self.options[alias]["READ_ONLY"])

    def engine(self, alias: str = DEFAULT_DB_ALIAS) -> Engine:
        if alias not in self.urls:
            raise DatabaseConfigError(f"La base {alias!r} no está configurada.", hint=f"Bases: {', '.join(self.urls)}.")
        if alias not in self._engines:
            self._engines[alias] = self._create_engine(self.urls[alias], self.options[alias])
        return self._engines[alias]

    @staticmethod
    def _create_engine(url: URL, options: dict[str, Any]) -> Engine:
        kwargs: dict[str, Any] = {"pool_pre_ping": True}  # descarta conexiones cortadas por el servidor
        if url.get_backend_name() == "sqlite":
            database = url.database or ""
            if database and database != ":memory:":
                Path(database).parent.mkdir(parents=True, exist_ok=True)
            kwargs["connect_args"] = {"check_same_thread": False}
            if not database or database == ":memory:":
                kwargs["poolclass"] = StaticPool  # una sola conexión: la base en memoria no se pierde
        elif options["CONN_MAX_AGE"]:
            kwargs["pool_recycle"] = options["CONN_MAX_AGE"]
        return create_engine(url, **kwargs)

    def dispose(self) -> None:
        for engine in self._engines.values():
            engine.dispose()

    # ------------------------------------------------------------------ modelos
    def register(self, base: Any, models: Iterable[type] | None = None) -> None:
        """Da a conocer los modelos de una `Base` de SQLAlchemy: `databases.register(Base)`.

        Asocia cada tabla con su modelo (y las tablas intermedias con el modelo al que apuntan), para
        enrutar también las consultas que no pasan por el ORM. También acepta (metadata, modelos).
        """
        metadata = _metadata(base)
        if models is None:
            models = [m.class_ for m in base.registry.mappers]
        by_table = {m.__table__: m for m in models if hasattr(m, "__table__")}
        self._tables.update(by_table)
        for table in metadata.tables.values():
            if table in self._tables:
                continue
            for fk in table.foreign_keys:  # tabla intermedia: va con el modelo al que apunta
                target = by_table.get(fk.column.table)
                if target is not None:
                    self._tables[table] = target
                    break

    def model_for_table(self, table: Any) -> type | None:
        return self._tables.get(table)

    def write_alias(self, model: Any, **hints: Any) -> str:
        alias = self.router.db_for_write(model, **hints)
        if self.is_read_only(alias):
            raise DatabaseConfigError(
                f"El router envía las escrituras de {model_meta(model).model_name} a la base {alias!r}, que es de solo lectura.",
                hint="Revise db_for_write: las escrituras deben ir a una base sin READ_ONLY (la primaria).",
            )
        return alias

    def check_relations(self, models: Iterable[type]) -> None:
        """Al arrancar: rechaza claves foráneas entre tablas que el router escribe en bases distintas."""
        by_table = {m.__table__: m for m in models if hasattr(m, "__table__")}
        for model in by_table.values():
            for fk in model.__table__.foreign_keys:
                target = by_table.get(fk.column.table) or self.model_for_table(fk.column.table)
                if target is None or target is model:
                    continue
                a, b = self.write_alias(model), self.write_alias(target)
                if a != b or not self.router.allow_relation(model, target):
                    raise DatabaseConfigError(
                        f"{model_meta(model).db_table} y {model_meta(target).db_table} están relacionadas "
                        f"(clave foránea), pero el router las escribe en bases distintas ({a!r} y {b!r}) "
                        "o allow_relation no lo permite.",
                        hint="Las tablas relacionadas deben estar en la misma base (igual que en Django).",
                    )

    def create_tables(
        self,
        base: Any,
        aliases: Iterable[str] | None = None,
        *,
        default_allowed: Iterable[str] | None = None,
    ) -> dict[str, list[str]]:
        """Crea las tablas que faltan en cada base donde `allow_migrate` lo permite (como `migrate`).

        Sin `aliases`, recorre todas las bases: sin opinión de los routers, crea las tablas solo en
        "default", y en las demás únicamente si un router lo pide. Con `aliases=["x"]` (como
        `migrate --database x`), las crea en esas bases salvo que un router lo prohíba. Nunca en las de
        solo lectura. Devuelve {alias: [tablas creadas o ya existentes]}.
        """
        metadata = _metadata(base)
        created: dict[str, list[str]] = {}
        targets = list(aliases) if aliases is not None else list(self.urls)
        if default_allowed is None:
            default_allowed = targets if aliases is not None else [DEFAULT_DB_ALIAS]
        assumed = set(default_allowed)
        for alias in targets:
            if self.is_read_only(alias):
                continue
            tables = []
            for table in metadata.sorted_tables:
                model = self.model_for_table(table)
                if model is None:
                    continue
                # "default" recibe las tablas salvo que un router lo prohíba; las demás bases, solo si un
                # router lo pide explícitamente (así nunca se crean tablas donde nadie las esperaba).
                opinion = self.router.allow_migrate_model(alias, model)
                if opinion or (opinion is None and alias in assumed):
                    tables.append(table)
            if tables:
                metadata.create_all(self.engine(alias), tables=tables)
                created[alias] = [t.name for t in tables]
        return created

    # ------------------------------------------------------------------ sesiones
    def session(self, *, write: bool = False, **kwargs: Any) -> RoutingSession:
        """Sesión de SQLAlchemy con enrutado. `write=True`: todo (también las lecturas) va a la base de escritura."""
        kwargs.setdefault("expire_on_commit", False)
        return RoutingSession(self, write=write, **kwargs)

    @contextmanager
    def atomic(self, **kwargs: Any) -> Iterator[RoutingSession]:
        """Sesión de escritura que confirma al salir sin errores y deshace si hay una excepción."""
        with self.session(write=True, **kwargs) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise


def _metadata(base: Any) -> MetaData:
    if isinstance(base, MetaData):
        return base
    metadata = getattr(base, "metadata", None)
    if not isinstance(metadata, MetaData):
        raise TypeError("Pase la Base declarativa de SQLAlchemy (o su metadata).")
    return metadata


class RoutingSession(Session):
    """Sesión que decide la base de cada consulta con el router (como el ORM de Django)."""

    def __init__(self, databases: Databases, *, write: bool = False, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.databases = databases
        self.write = write
        event.listen(self, "before_flush", _check_relations_before_flush)

    def _model_for(self, mapper: Any, clause: Any) -> type | None:
        if mapper is not None:
            model: type = mapper.class_
            return model
        if clause is not None:
            for table in find_tables(clause, include_aliases=True, include_crud=True):
                found = self.databases.model_for_table(table)
                if found is not None:
                    return found
        return None

    def get_bind(self, mapper: Any = None, *, clause: Any = None, **kwargs: Any) -> Engine:
        model = self._model_for(mapper, clause)
        if model is None:
            return self.databases.engine(DEFAULT_DB_ALIAS)
        writing = self.write or self._flushing or bool(getattr(clause, "is_dml", False))
        alias = self.databases.write_alias(model) if writing else self.databases.router.db_for_read(model)
        return self.databases.engine(alias)


def _check_relations_before_flush(session: Session, flush_context: Any, instances: Any) -> None:
    """Antes de guardar: `allow_relation` para cada objeto relacionado (Django lo hace al asignar)."""
    if not isinstance(session, RoutingSession) or not session.databases.router.routers:
        return
    router = session.databases.router
    for obj in [*session.new, *session.dirty]:
        mapper = getattr(type(obj), "__mapper__", None)
        if mapper is None:
            continue
        for rel in mapper.relationships:
            value = obj.__dict__.get(rel.key)
            if value is None:
                continue
            for other in value if isinstance(value, list | set | tuple) else (value,):
                if not router.allow_relation(obj, other):
                    raise ValueError(
                        f"No se puede relacionar {model_meta(obj).model_name} con {model_meta(other).model_name}: "
                        f"el router no permite esa relación (bases {router.db_for_write(obj)!r} y "
                        f"{router.db_for_write(other)!r})."
                    )
