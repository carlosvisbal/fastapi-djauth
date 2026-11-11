"""Varias bases y routers (DATABASES + DATABASE_ROUTERS de Django) y sus seguros."""

from __future__ import annotations

from collections import Counter

import pytest
from sqlalchemy import ForeignKey, Integer, String, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from djauth import AuthKit, AuthSettings, BaseRouter, DatabaseConfigError, Databases, model_meta

PWD = "Clave-Segura-2026"


class PrimaryReplicaRouter:
    """Router tal como se escribe en Django: lecturas a la réplica, escrituras a la primaria."""

    def db_for_read(self, model, **hints):
        return "replica"

    def db_for_write(self, model, **hints):
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return db == "default"


def count_queries(kit: AuthKit) -> Counter:
    """Cuántas consultas recibe cada base."""
    counter: Counter = Counter()
    for alias in kit.databases.aliases:
        engine = kit.databases.engine(alias)
        event.listen(engine, "before_cursor_execute", lambda *a, alias=alias, **k: counter.update([alias]))
    return counter


@pytest.fixture
def replicated(tmp_path):
    """Primaria y "réplica" apuntando al mismo archivo (la réplica sí tiene los datos), con motores distintos."""
    url = f"sqlite:///{tmp_path / 'auth.sqlite3'}"
    kit = AuthKit(
        AuthSettings(
            databases={
                "default": url,
                "replica": {"ENGINE": "sqlite", "NAME": str(tmp_path / "auth.sqlite3"), "READ_ONLY": True},
            },
            database_routers=[PrimaryReplicaRouter],
            password_iterations=1000,
            bootstrap_superuser=("admin", PWD, ""),
        )
    ).init()
    return kit


def test_reads_go_to_the_replica_and_writes_to_the_primary(replicated):
    kit = replicated
    queries = count_queries(kit)
    kit.list_users()
    kit.list_groups()
    assert queries["replica"] > 0 and queries["default"] == 0
    queries.clear()
    user = kit.create_user("ana", PWD + "x")
    kit.update_user(user["id"], {"first_name": "Ana"})
    assert queries["default"] > 0 and queries["replica"] == 0


def test_security_reads_never_use_the_replica(replicated):
    """Contraseñas, sesiones y tokens se validan siempre en la primaria: una réplica atrasada no puede
    aceptar una contraseña vieja ni un token ya revocado."""
    kit = replicated
    queries = count_queries(kit)
    user = kit.authenticate(username="admin", password=PWD)
    token = kit.login(user, kind="bearer")
    assert kit.user_from_token(token, "bearer").username == "admin"
    kit.logout(token)
    kit._invalidate()
    assert kit.user_from_token(token, "bearer") is None
    assert queries["replica"] == 0


def test_read_only_database_never_receives_writes(tmp_path):
    class WritesToReplica(PrimaryReplicaRouter):
        def db_for_write(self, model, **hints):
            return "replica"

    with pytest.raises(DatabaseConfigError, match="solo lectura"):
        AuthKit(
            AuthSettings(
                databases={"default": "sqlite://", "replica": {"ENGINE": "sqlite", "NAME": "", "READ_ONLY": True}},
                database_routers=[WritesToReplica],
            )
        )


def test_router_returning_an_unknown_database_is_an_error():
    class Typo(BaseRouter):
        def db_for_write(self, model, **hints):
            return "primaria"

    with pytest.raises(DatabaseConfigError, match="primaria") as exc:
        AuthKit(AuthSettings(databases={"default": "sqlite://"}, database_routers=[Typo]))
    assert "default" in exc.value.hint


def test_djauth_tables_cannot_be_split_across_databases():
    class SplitSessions(BaseRouter):
        def db_for_write(self, model, **hints):
            return "otra" if model._meta.app_label == "sessions" else None

    with pytest.raises(DatabaseConfigError, match="una sola base"):
        AuthKit(AuthSettings(databases={"default": "sqlite://", "otra": "sqlite://"}, database_routers=[SplitSessions]))


def test_djauth_in_its_own_database_like_djangos_auth_router(tmp_path):
    """El router de la documentación de Django ("AuthRouter") funciona tal cual."""

    class AuthRouter:
        route_app_labels = frozenset({"auth", "contenttypes", "sessions", "admin"})

        def db_for_read(self, model, **hints):
            return "auth_db" if model._meta.app_label in self.route_app_labels else None

        def db_for_write(self, model, **hints):
            return "auth_db" if model._meta.app_label in self.route_app_labels else None

        def allow_relation(self, obj1, obj2, **hints):
            if obj1._meta.app_label in self.route_app_labels or obj2._meta.app_label in self.route_app_labels:
                return True
            return None

        def allow_migrate(self, db, app_label, model_name=None, **hints):
            if app_label in self.route_app_labels:
                return db == "auth_db"
            return None

    kit = AuthKit(
        AuthSettings(
            databases={"default": f"sqlite:///{tmp_path / 'app.sqlite3'}", "auth_db": f"sqlite:///{tmp_path / 'auth.sqlite3'}"},
            database_routers=[AuthRouter()],
            password_iterations=1000,
        )
    ).init()
    kit.create_user("ana", PWD)
    assert kit.db_alias == "auth_db"
    assert not (tmp_path / "app.sqlite3").exists() or (tmp_path / "app.sqlite3").stat().st_size == 0
    assert kit.authenticate(username="ana", password=PWD) is not None


def test_allow_migrate_false_skips_table_creation(tmp_path):
    class NoLog(BaseRouter):
        def allow_migrate(self, db, app_label, model_name=None, **hints):
            return False if model_name == "logentry" else None

    kit = AuthKit(AuthSettings(database_url=f"sqlite:///{tmp_path / 'a.sqlite3'}", database_routers=[NoLog])).init()
    from sqlalchemy import inspect

    tables = set(inspect(kit.engine).get_table_names())
    assert "auth_user" in tables and "auth_log" not in tables


# ---------------------------------------------------------------------- modelos de la aplicación
class Base(DeclarativeBase):
    pass


class Cliente(Base):
    __tablename__ = "clientes"
    __app_label__ = "ventas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100))


class Pedido(Base):
    __tablename__ = "pedidos"
    __app_label__ = "ventas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"))
    cliente: Mapped[Cliente] = relationship()


class Lectura(Base):
    __tablename__ = "lecturas"
    __app_label__ = "sensores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    valor: Mapped[str] = mapped_column(String(20))


class ByApp(BaseRouter):
    def db_for_read(self, model, **hints):
        return {"ventas": "ventas", "sensores": "sensores"}.get(model._meta.app_label)

    db_for_write = db_for_read

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return {"ventas": "ventas", "sensores": "sensores"}.get(app_label) == db


def test_application_models_in_several_databases(tmp_path):
    dbs = Databases(
        {
            "default": f"sqlite:///{tmp_path / 'default.sqlite3'}",
            "ventas": f"sqlite:///{tmp_path / 'ventas.sqlite3'}",
            "sensores": f"sqlite:///{tmp_path / 'sensores.sqlite3'}",
        },
        [ByApp()],
    )
    dbs.register(Base)  # todos los modelos de la Base
    dbs.check_relations([Cliente, Pedido, Lectura])
    created = dbs.create_tables(Base)
    assert created == {"ventas": ["clientes", "pedidos"], "sensores": ["lecturas"]}

    with dbs.atomic() as s:  # una sola sesión, dos bases
        s.add(Pedido(cliente=Cliente(nombre="Acme")))
        s.add(Lectura(valor="21.5"))
    with dbs.session() as s:
        assert s.scalars(select(Pedido)).one().cliente.nombre == "Acme"
        assert s.scalar(select(Lectura.valor)) == "21.5"
    assert model_meta(Pedido).app_label == "ventas"


def test_foreign_keys_across_databases_are_rejected_at_startup(tmp_path):
    class SplitVentas(BaseRouter):
        def db_for_write(self, model, **hints):
            return "otra" if model is Cliente else None

    dbs = Databases({"default": "sqlite://", "otra": "sqlite://"}, [SplitVentas()])
    dbs.register(Base.metadata, [Cliente, Pedido, Lectura])
    with pytest.raises(DatabaseConfigError, match="bases distintas") as exc:
        dbs.check_relations([Cliente, Pedido, Lectura])
    assert "misma base" in exc.value.hint


def test_allow_relation_is_checked_before_saving():
    class NoMixing(BaseRouter):
        def allow_relation(self, obj1, obj2, **hints):
            return False

    dbs = Databases({"default": "sqlite://"}, [NoMixing()])
    dbs.register(Base.metadata, [Cliente, Pedido, Lectura])
    Base.metadata.create_all(dbs.engine())
    with dbs.session(write=True) as s:
        s.add(Pedido(cliente=Cliente(nombre="X")))
        with pytest.raises(ValueError, match="no permite esa relación"):
            s.flush()


def test_databases_requires_default_and_valid_aliases():
    with pytest.raises(DatabaseConfigError, match="default"):
        Databases({"primaria": "sqlite://"})
    with pytest.raises(DatabaseConfigError, match="Alias"):
        Databases({"default": "sqlite://", "mala base": "sqlite://"})


def test_create_tables_on_an_explicit_database_like_migrate_database(tmp_path):
    dbs = Databases({"default": "sqlite://", "otra": f"sqlite:///{tmp_path / 'otra.sqlite3'}"})
    dbs.register(Base)
    assert dbs.create_tables(Base) == {"default": ["clientes", "lecturas", "pedidos"]}
    assert dbs.create_tables(Base, aliases=["otra"]) == {"otra": ["clientes", "lecturas", "pedidos"]}
