"""Tablas (SQLAlchemy 2). Misma estructura que `django.contrib.auth`: usuario, grupo, permiso y sus
relaciones, más sesiones y el registro de acciones de la administración."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def build_models(prefix: str = "auth_", user_mixin: type | None = None) -> Any:
    """Crea las clases con el prefijo de tabla indicado (cada `AuthKit` tiene su propio metadata).

    `user_mixin` aporta columnas propias al usuario (como heredar de `AbstractUser` en Django).
    """

    class Base(DeclarativeBase):
        pass

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
        id: Mapped[int] = mapped_column(primary_key=True)
        app_label: Mapped[str] = mapped_column(String(100))
        codename: Mapped[str] = mapped_column(String(100))
        name: Mapped[str] = mapped_column(String(255))

        @property
        def key(self) -> str:
            return f"{self.app_label}.{self.codename}"

    class Group(Base):
        __tablename__ = f"{prefix}group"
        id: Mapped[int] = mapped_column(primary_key=True)
        name: Mapped[str] = mapped_column(String(150), unique=True)
        permissions: Mapped[list[Permission]] = relationship(secondary=t_group_permissions, lazy="selectin")

    user_bases = (user_mixin, Base) if user_mixin is not None else (Base,)

    class User(*user_bases):
        __tablename__ = f"{prefix}user"
        id: Mapped[int] = mapped_column(primary_key=True)
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
        id: Mapped[int] = mapped_column(primary_key=True)
        action_time: Mapped[datetime] = mapped_column(DateTime, index=True)
        user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
        username: Mapped[str] = mapped_column(String(150), default="")
        action: Mapped[str] = mapped_column(String(30))
        object_type: Mapped[str] = mapped_column(String(50), default="")
        object_id: Mapped[str] = mapped_column(String(50), default="")
        object_repr: Mapped[str] = mapped_column(String(200), default="")
        message: Mapped[str] = mapped_column(Text, default="")

    class Meta(Base):
        __tablename__ = f"{prefix}meta"
        key: Mapped[str] = mapped_column(String(50), primary_key=True)
        value: Mapped[str] = mapped_column(Text)

    class Models:
        pass

    m = Models()
    m.Base, m.User, m.Group, m.Permission, m.Session, m.LogEntry, m.Meta = Base, User, Group, Permission, Session, LogEntry, Meta
    return m
