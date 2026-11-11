"""Tablas (SQLAlchemy 2). Misma estructura que `django.contrib.auth`: usuario, grupo, permiso y sus
relaciones, más sesiones, el registro de acciones de la administración y el historial de cambios
de los usuarios."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.orm.attributes import set_committed_value

from djauth.routers import ModelMeta


def build_models(prefix: str = "auth_", user_mixin: type | None = None, *, empty_string_is_null: bool = False) -> Any:
    """Crea las clases con el prefijo de tabla indicado (cada `AuthKit` tiene su propio metadata).

    `user_mixin` aporta columnas propias al usuario (como heredar de `AbstractUser` en Django).
    `empty_string_is_null`: para Oracle, que guarda `''` como NULL (ver `allow_empty_strings_as_null`).
    """

    class Base(DeclarativeBase):
        pass

    # Identity(): clave autoincremental en todos los motores (Oracle no tiene otra forma; en SQLite y
    # MySQL equivale a su autoincremento de siempre).

    def fk(table: str) -> ForeignKey:
        return ForeignKey(f"{prefix}{table}.id", ondelete="CASCADE")

    t_user_groups = Table(
        f"{prefix}user_groups",
        Base.metadata,
        Column("user_id", Integer, fk("user"), primary_key=True),
        Column("group_id", Integer, fk("group"), primary_key=True),
    )
    t_user_permissions = Table(
        f"{prefix}user_user_permissions",
        Base.metadata,
        Column("user_id", Integer, fk("user"), primary_key=True),
        Column("permission_id", Integer, fk("permission"), primary_key=True),
    )
    t_group_permissions = Table(
        f"{prefix}group_permissions",
        Base.metadata,
        Column("group_id", Integer, fk("group"), primary_key=True),
        Column("permission_id", Integer, fk("permission"), primary_key=True),
    )

    class Permission(Base):
        __tablename__ = f"{prefix}permission"
        __table_args__ = (UniqueConstraint("app_label", "codename"),)
        id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
        app_label: Mapped[str] = mapped_column(String(100))
        codename: Mapped[str] = mapped_column(String(100))
        name: Mapped[str] = mapped_column(String(255))

        @property
        def key(self) -> str:
            return f"{self.app_label}.{self.codename}"

    class Group(Base):
        __tablename__ = f"{prefix}group"
        id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
        name: Mapped[str] = mapped_column(String(150), unique=True)
        permissions: Mapped[list[Permission]] = relationship(secondary=t_group_permissions, lazy="selectin")

    user_bases = (user_mixin, Base) if user_mixin is not None else (Base,)

    class User(*user_bases):  # type: ignore[misc]
        __tablename__ = f"{prefix}user"
        id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
        username: Mapped[str] = mapped_column(String(150), unique=True, index=True)
        password: Mapped[str] = mapped_column(String(255))
        email: Mapped[str] = mapped_column(String(254), default="")
        first_name: Mapped[str] = mapped_column(String(150), default="")
        last_name: Mapped[str] = mapped_column(String(150), default="")
        is_active: Mapped[bool] = mapped_column(Boolean, default=True)
        is_staff: Mapped[bool] = mapped_column(Boolean, default=False)
        is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
        last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
        date_joined: Mapped[datetime] = mapped_column(DateTime)
        extra: Mapped[dict] = mapped_column(JSON, default=dict)
        groups: Mapped[list[Group]] = relationship(secondary=t_user_groups, lazy="selectin")
        user_permissions: Mapped[list[Permission]] = relationship(secondary=t_user_permissions, lazy="selectin")

    class Session(Base):
        __tablename__ = f"{prefix}session"
        key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
        user_id: Mapped[int] = mapped_column(fk("user"), index=True)
        kind: Mapped[str] = mapped_column(String(10), default="session")  # session | bearer
        backend: Mapped[str] = mapped_column(String(200), default="")  # backend que autenticó al usuario
        created: Mapped[datetime] = mapped_column(DateTime)
        expires: Mapped[datetime] = mapped_column(DateTime, index=True)
        ip: Mapped[str] = mapped_column(String(64), default="")
        user_agent: Mapped[str] = mapped_column(String(255), default="")

    class LogEntry(Base):
        __tablename__ = f"{prefix}log"
        id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
        action_time: Mapped[datetime] = mapped_column(DateTime, index=True)
        user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
        username: Mapped[str] = mapped_column(String(150), default="")
        action: Mapped[str] = mapped_column(String(30))
        object_type: Mapped[str] = mapped_column(String(50), default="")
        object_id: Mapped[str] = mapped_column(String(50), default="")
        object_repr: Mapped[str] = mapped_column(String(200), default="")
        message: Mapped[str] = mapped_column(Text, default="")

    class UserChange(Base):
        """Historial de cambios del usuario: solo modificaciones de sus datos, campo por campo.

        Sin clave foránea a propósito: el historial de un usuario sobrevive a su eliminación.
        """

        __tablename__ = f"{prefix}user_history"
        id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
        changed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
        user_id: Mapped[int] = mapped_column(Integer, index=True)
        user_repr: Mapped[str] = mapped_column(String(150), default="")
        action: Mapped[str] = mapped_column(String(20))  # create | update | password | delete
        changes: Mapped[dict] = mapped_column(JSON, default=dict)  # {campo: {"old": …, "new": …}}
        fields: Mapped[str] = mapped_column(Text, default="")  # ",email,is_active," para filtrar por campo
        actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
        actor_repr: Mapped[str] = mapped_column(String(150), default="")
        reason: Mapped[str] = mapped_column(String(255), default="")
        ip: Mapped[str] = mapped_column(String(64), default="")

    class Meta(Base):
        __tablename__ = f"{prefix}meta"
        key: Mapped[str] = mapped_column(String(50), primary_key=True)
        value: Mapped[str] = mapped_column(Text)

    class Models:
        pass

    m: Any = Models()
    m.Base, m.User, m.Group, m.Permission, m.Session, m.LogEntry, m.Meta = Base, User, Group, Permission, Session, LogEntry, Meta
    m.UserChange = UserChange
    # `_meta` con las mismas app_label que Django (auth, sessions, admin): un router escrito para Django
    # que mire model._meta.app_label funciona igual.
    for cls, app_label, model_name in (
        (User, "auth", "user"),
        (Group, "auth", "group"),
        (Permission, "auth", "permission"),
        (UserChange, "auth", "userchange"),
        (Meta, "auth", "meta"),
        (Session, "sessions", "session"),
        (LogEntry, "admin", "logentry"),
    ):
        cls._meta = ModelMeta(app_label=app_label, model_name=model_name, db_table=cls.__tablename__)
    m.all = (User, Group, Permission, Session, LogEntry, UserChange, Meta)
    if empty_string_is_null:
        allow_empty_strings_as_null(Base)
    return m


def allow_empty_strings_as_null(base: Any) -> None:
    """Oracle guarda `''` como NULL. Como hace Django con Oracle, los textos cuyo valor por defecto es
    `''` admiten NULL en la tabla, y al leerlos NULL vuelve a ser `''`: el resto del código ve lo mismo
    en todos los motores. Incluye las columnas propias del usuario (`user_mixin`)."""
    text_columns: dict[type, list[str]] = {}
    for mapper in base.registry.mappers:
        names = []
        for column in mapper.local_table.columns:
            default = column.default
            if (
                isinstance(column.type, String)
                and not column.primary_key
                and default is not None
                and getattr(default, "is_scalar", False)
                and default.arg == ""
            ):
                column.nullable = True
                names.append(mapper.get_property_by_column(column).key)
        if names:
            text_columns[mapper.class_] = names

    def restore(target: Any, *_: Any) -> None:
        for name in text_columns.get(type(target), ()):
            if target.__dict__.get(name, "") is None:
                set_committed_value(target, name, "")

    event.listen(base, "load", restore, propagate=True)
    event.listen(base, "refresh", restore, propagate=True)
