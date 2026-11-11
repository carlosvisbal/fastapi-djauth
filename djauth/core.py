"""Núcleo del módulo: usuarios, grupos (roles), permisos, sesiones y registro de acciones.

No depende de FastAPI: se puede usar desde un script, una tarea o cualquier framework. Las funciones
devuelven datos simples (`AuthUser`, diccionarios), nunca objetos del ORM.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import threading
import time
from collections import deque
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from inspect import signature as inspect_signature
from typing import Any

from sqlalchemy import delete, func, inspect, or_, select, text
from sqlalchemy.orm import Session as OrmSession

from djauth import hashers
from djauth.backends import AuthRequest, BaseBackend, load_backend
from djauth.database import DatabaseConfigError
from djauth.errors import (
    InvalidCredentialsError,
    NotFoundError,
    PermissionDeniedError,
    TooManyAttemptsError,
    ValidationError,
)
from djauth.fields import UserField, to_json, user_fields
from djauth.models import allow_empty_strings_as_null, build_models
from djauth.routers import Databases
from djauth.settings import AuthSettings
from djauth.validators import normalize_email, validate_password, validate_username

logger = logging.getLogger("djauth")

# IP de la petición en curso: la fija la API para que el historial de cambios la anote sin tener que
# pasarla a cada método. Fuera de una petición (scripts, comandos) queda vacía.
request_ip: ContextVar[str] = ContextVar("djauth_request_ip", default="")

# Campos del usuario que registra el historial, con su nombre para mostrar. La contraseña nunca se
# guarda (solo que cambió); `last_login` y `date_joined` no son cambios hechos por una persona.
HISTORY_FIELDS = {
    "username": "Usuario",
    "email": "Correo",
    "first_name": "Nombre",
    "last_name": "Apellidos",
    "is_active": "Activo",
    "is_staff": "Acceso a la administración",
    "is_superuser": "Superusuario",
    "groups": "Grupos",
    "permissions": "Permisos",
}
HISTORY_ACTIONS = ("create", "update", "password", "delete")
HIDDEN = {"hidden": True}  # valor de un campo sensible o de la contraseña en el historial

# Permisos propios de la administración, con los mismos nombres que usa Django.
BUILTIN_PERMISSIONS = {
    "auth": {
        "view_user": "Puede ver usuarios",
        "add_user": "Puede agregar usuarios",
        "change_user": "Puede modificar usuarios",
        "delete_user": "Puede eliminar usuarios",
        "view_group": "Puede ver grupos",
        "add_group": "Puede agregar grupos",
        "change_group": "Puede modificar grupos",
        "delete_group": "Puede eliminar grupos",
        "view_permission": "Puede ver permisos",
        "add_permission": "Puede agregar permisos",
        "change_permission": "Puede modificar permisos",
        "delete_permission": "Puede eliminar permisos",
        "view_logentry": "Puede ver el registro de acciones",
        "view_userchange": "Puede ver el historial de cambios de usuarios",
    }
}

# Aplicaciones de djauth (las mismas `app_label` de Django): nadie crea permisos con ellas desde la API.
RESERVED_APP_LABELS = frozenset({"auth", "sessions", "admin"})
# `app_label` y `codename`: minúsculas, números y guion bajo, empezando por letra (como en Django).
PERMISSION_PART = re.compile(r"^[a-z][a-z0-9_]{0,99}$")


def now() -> datetime:
    return datetime.now()


@dataclass(frozen=True)
class AuthUser:
    """Usuario autenticado, con la misma interfaz que el `User` de Django para consultar permisos."""

    id: int
    username: str
    email: str = ""
    first_name: str = ""
    last_name: str = ""
    is_active: bool = True
    is_staff: bool = False
    is_superuser: bool = False
    last_login: datetime | None = None
    date_joined: datetime | None = None
    groups: tuple[str, ...] = ()
    permissions: frozenset[str] = frozenset()
    extra: dict[str, Any] = field(default_factory=dict)
    is_service: bool = False  # credencial de máquina (llave de API), no una persona
    backend: str = ""  # backend que autenticó al usuario (como `user.backend` en Django)
    fields: dict[str, Any] = field(default_factory=dict)  # columnas propias (user_mixin)

    def __getattr__(self, name: str) -> Any:
        # Las columnas propias se leen como atributos: `user.telefono`.
        fields = self.__dict__.get("fields") or {}
        if name in fields:
            return fields[name]
        raise AttributeError(f"'AuthUser' no tiene el atributo {name!r}")

    is_authenticated = True
    is_anonymous = False

    def has_perm(self, perm: str) -> bool:
        return self.is_active and (self.is_superuser or perm in self.permissions)

    def has_perms(self, perms: Iterable[str]) -> bool:
        return all(self.has_perm(p) for p in perms)

    def has_module_perms(self, app_label: str) -> bool:
        return self.is_active and (self.is_superuser or any(p.startswith(f"{app_label}.") for p in self.permissions))

    def get_all_permissions(self) -> frozenset[str]:
        return self.permissions

    def get_full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self) -> str:
        return self.first_name

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": self.get_full_name(),
            "is_active": self.is_active,
            "is_staff": self.is_staff,
            "is_superuser": self.is_superuser,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "date_joined": self.date_joined.isoformat() if self.date_joined else None,
            "groups": list(self.groups),
            "permissions": sorted(self.permissions),
            "extra": self.extra,
            **self.fields,
        }


SERVICE_USER = AuthUser(id=0, username="api-key", is_superuser=True, is_service=True)


class AuthKit:
    def __init__(self, settings: AuthSettings | None = None) -> None:
        self.settings = settings or AuthSettings()
        s = self.settings
        # Una o varias bases (DATABASES) y sus routers (DATABASE_ROUTERS). Ver djauth.routers.
        config = s.databases or {"default": s.database or s.database_url}
        self.databases = Databases(config, s.database_routers, conn_max_age=s.database_conn_max_age)
        self.models = build_models(s.table_prefix, s.user_mixin)
        self.databases.register(self.models.Base.metadata, self.models.all)
        # Todas las tablas de djauth se escriben en una sola base: así un cambio y su historial se
        # guardan juntos (atómicos) y las relaciones usuario–grupo–permiso son posibles.
        write_aliases = {self.databases.write_alias(m): m for m in self.models.all}
        if len(write_aliases) > 1:
            detail = ", ".join(f"{m._meta.model_name} → {a!r}" for a, m in write_aliases.items())
            raise DatabaseConfigError(
                f"Las tablas de djauth deben escribirse en una sola base, pero el router las reparte ({detail}).",
                hint="Haga que db_for_write devuelva la misma base para app_label auth, sessions y admin. "
                "Las lecturas sí pueden ir a réplicas.",
            )
        self.db_alias: str = next(iter(write_aliases))
        self.databases.check_relations(self.models.all)
        if self.databases.urls[self.db_alias].get_backend_name() == "oracle":
            allow_empty_strings_as_null(self.models.Base)  # Oracle guarda '' como NULL
        self.custom_fields: tuple[UserField, ...] = user_fields(self.models.User)
        if self.settings.username_field not in ("username", "email"):
            raise ValueError(f'username_field debe ser "username" o "email" (recibido: {self.settings.username_field!r})')
        self.email_login = self.settings.username_field == "email"
        samesite = self.settings.session_cookie_samesite
        if samesite not in ("lax", "strict", "none"):
            raise ValueError(f'session_cookie_samesite debe ser "lax", "strict" o "none" (recibido: {samesite!r})')
        if samesite == "none" and not self.settings.session_cookie_secure:
            raise ValueError('session_cookie_samesite="none" exige session_cookie_secure=True (los navegadores lo piden)')
        if not self.settings.authentication_backends:
            raise ValueError("authentication_backends no puede estar vacío")
        self.backends: list[tuple[str, BaseBackend]] = [load_backend(b) for b in self.settings.authentication_backends]
        for _, backend in self.backends:
            backend.kit = self
        self.engine = self.databases.engine(self.db_alias)  # base donde viven las tablas de djauth
        self._initialized = False
        self._registry: dict[str, dict[str, str]] = {a: dict(p) for a, p in BUILTIN_PERMISSIONS.items()}
        for app_label, perms in self.settings.permissions.items():
            self.register_permissions(app_label, perms)
        self._cache: dict[str, tuple[float, AuthUser]] = {}
        self._cache_lock = threading.Lock()
        self._failures: dict[tuple[str, str], deque[float]] = {}
        self._secret: str | None = self.settings.secret_key

    # ================================================================== arranque
    def register_permissions(self, app_label: str, permissions: dict[str, str]) -> None:
        """Declara permisos del proyecto, p. ej. `("ventas", {"aprobar_pedido": "Puede aprobar pedidos"})`."""
        self._registry.setdefault(app_label, {}).update(permissions)
        if self._initialized:
            self._sync_permissions()

    def init(self) -> AuthKit:
        """Crea las tablas que falten, sincroniza los permisos declarados y el superusuario inicial."""
        self.databases.create_tables(self.models.Base.metadata, aliases=[self.db_alias], default_allowed=[self.db_alias])
        self._upgrade_schema()
        if self.email_login:
            self._ensure_unique_email_index()
        self._purge_orphans()
        self._initialized = True
        self._sync_permissions()
        boot = self.settings.bootstrap_superuser
        if boot and boot[0] and boot[1]:
            with self._db() as db:
                empty = db.scalar(select(func.count()).select_from(self.models.User)) == 0
            if empty:
                email = boot[2] if len(boot) > 2 else ""
                identifier = (email or boot[0]) if self.email_login else boot[0]
                self.create_superuser(
                    identifier,
                    boot[1],
                    email=email or identifier if self.email_login else email,
                    validate=False,
                    reason="Superusuario inicial (bootstrap_superuser).",
                )
        return self

    def _upgrade_schema(self) -> None:
        """Añade a las tablas existentes las columnas nuevas (campos propios agregados después).

        Solo agrega: renombrar o quitar columnas requiere una herramienta de migraciones (Alembic).
        Las columnas se crean admitiendo nulos para no fallar con los registros que ya existen.
        """
        inspector = inspect(self.engine)
        dialect = self.engine.dialect
        quote = dialect.identifier_preparer.quote  # comillas del motor: "x" en PostgreSQL, `x` en MySQL…
        # Sintaxis de cada motor para agregar una columna.
        add = {"oracle": "ADD ({column} {ddl})", "mssql": "ADD {column} {ddl}"}.get(dialect.name, "ADD COLUMN {column} {ddl}")
        with self.engine.begin() as conn:
            for table in self.models.Base.metadata.sorted_tables:
                if not inspector.has_table(table.name):
                    continue
                present = {c["name"] for c in inspector.get_columns(table.name)}
                for column in table.columns:
                    if column.name in present:
                        continue
                    # Los nombres vienen de los modelos (código del proyecto), nunca de una petición, y
                    # van entre las comillas del motor.
                    clause = add.format(column=quote(column.name), ddl=column.type.compile(dialect=dialect))
                    conn.execute(text(f"ALTER TABLE {quote(table.name)} {clause}"))
                    default = column.default.arg if column.default is not None and column.default.is_scalar else None
                    if default is not None:
                        conn.execute(table.update().values({column.name: default}))
                    logger.info("djauth: columna %s.%s añadida", table.name, column.name)

    def _purge_orphans(self) -> None:
        """Quita membresías y asignaciones que apuntan a grupos o permisos que ya no existen.

        Versiones anteriores a la 1.5.0 dejaban esas filas en SQLite al eliminar un grupo, y el
        siguiente grupo creado podía reutilizar el id y heredar a esos miembros.
        """
        M = self.models
        user_groups = M.User.groups.property.secondary
        user_perms = M.User.user_permissions.property.secondary
        group_perms = M.Group.permissions.property.secondary
        pairs = [
            (user_groups, "group_id", M.Group),
            (user_groups, "user_id", M.User),
            (user_perms, "permission_id", M.Permission),
            (user_perms, "user_id", M.User),
            (group_perms, "permission_id", M.Permission),
            (group_perms, "group_id", M.Group),
            (M.Session.__table__, "user_id", M.User),
        ]
        with self.engine.begin() as conn:
            for table, column, target in pairs:
                result = conn.execute(delete(table).where(table.c[column].not_in(select(target.id))))
                if result.rowcount:
                    logger.warning("djauth: %s filas huérfanas quitadas de %s", result.rowcount, table.name)

    def _ensure_unique_email_index(self) -> None:
        """Con inicio de sesión por correo, la base garantiza que no haya dos usuarios con el mismo
        correo (sin distinguir mayúsculas), aun con peticiones simultáneas. SQLite y PostgreSQL."""
        if self.engine.dialect.name not in ("sqlite", "postgresql"):
            return  # en otros motores lo comprueba la aplicación al guardar
        table = self.models.User.__tablename__
        ddl = f'CREATE UNIQUE INDEX IF NOT EXISTS "{table}_email_lower_uniq" ON "{table}" (lower(email)) WHERE email <> \'\''
        try:
            with self.engine.begin() as conn:
                conn.execute(text(ddl))
        except Exception as exc:  # noqa: BLE001 - p. ej. correos repetidos de antes de activar el modo
            logger.warning(
                "djauth: no se pudo crear el índice único de correo (%s). "
                "Hay correos repetidos: corríjalos en la administración.",
                exc,
            )

    @contextmanager
    def _db(self, *, read: bool = False) -> Iterator[OrmSession]:
        """Sesión de base de datos. Por defecto, de escritura: todo va a la base de escritura (la
        primaria), también las lecturas, así que nunca se modifica ni se valida (contraseñas, sesiones,
        tokens) un dato leído de una réplica atrasada. `read=True` solo en consultas de consulta pura
        (listados de la administración), que el router puede enviar a una réplica."""
        with self.databases.session(write=not read) as db:
            yield db

    def _sync_permissions(self) -> None:
        P = self.models.Permission
        with self._db() as db:
            existing = {(p.app_label, p.codename): p for p in db.scalars(select(P))}
            for app_label, perms in self._registry.items():
                for codename, name in perms.items():
                    row = existing.get((app_label, codename))
                    if row is None:
                        db.add(P(app_label=app_label, codename=codename, name=name))
                    elif row.name != name:
                        row.name = name
            db.commit()

    @property
    def secret(self) -> str:
        if self._secret is None:
            M = self.models.Meta
            with self._db() as db:
                row = db.get(M, "secret_key")
                if row is None:
                    row = M(key="secret_key", value=secrets.token_urlsafe(48))
                    db.add(row)
                    db.commit()
                self._secret = row.value
        return self._secret

    # ================================================================== conversión
    def _auth_user(self, u: Any, backend: str = "") -> AuthUser:
        # Como `has_perm` en Django: los permisos son la suma de lo que concede cada backend.
        perms: set[str] = set()
        for _, b in self.backends:
            perms |= b.get_all_permissions(u)
        return AuthUser(
            id=u.id,
            username=u.username,
            email=u.email or "",
            first_name=u.first_name or "",
            last_name=u.last_name or "",
            is_active=u.is_active,
            is_staff=u.is_staff,
            is_superuser=u.is_superuser,
            last_login=u.last_login,
            date_joined=u.date_joined,
            groups=tuple(sorted(g.name for g in u.groups)),
            permissions=frozenset(perms),
            extra=dict(u.extra or {}),
            backend=backend,
            fields={f.name: to_json(getattr(u, f.name, None)) for f in self.custom_fields},
        )

    def _user_dict(self, u: Any) -> dict[str, Any]:
        """Usuario para la administración: incluye los ids de grupos y permisos directos."""
        data = self._auth_user(u).to_dict()
        data.update(
            group_ids=sorted(g.id for g in u.groups),
            permission_ids=sorted(p.id for p in u.user_permissions),
            has_usable_password=hashers.is_password_usable(u.password),
        )
        return data

    @staticmethod
    def _group_dict(g: Any, members: int | None = None) -> dict[str, Any]:
        data = {
            "id": g.id,
            "name": g.name,
            "permission_ids": sorted(p.id for p in g.permissions),
            "permissions": sorted(p.key for p in g.permissions),
        }
        if members is not None:
            data["members"] = members
        return data

    def _invalidate(self) -> None:
        with self._cache_lock:
            self._cache.clear()

    def _log(
        self, db: OrmSession, actor: AuthUser | None, action: str, obj_type: str = "", obj: Any = None, message: str = ""
    ) -> None:
        db.add(
            self.models.LogEntry(
                action_time=now(),
                user_id=actor.id if actor else None,
                username=actor.username if actor else "",
                action=action,
                object_type=obj_type,
                object_id=str(getattr(obj, "id", "") or ""),
                # Usuario: su nombre de usuario; permiso: `app.codename`; grupo: su nombre.
                object_repr=str(next((v for a in ("username", "key", "name") if (v := getattr(obj, a, None))), ""))[:200],
                message=message[:2000],
            )
        )

    # ================================================================== historial de cambios del usuario
    def _user_snapshot(self, user: Any) -> dict[str, Any]:
        """Valores auditables del usuario (sin contraseña), listos para JSON."""
        snap: dict[str, Any] = {
            "username": user.username,
            "email": user.email or "",
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "is_active": bool(user.is_active),
            "is_staff": bool(user.is_staff),
            "is_superuser": bool(user.is_superuser),
            "groups": sorted(g.name for g in user.groups),
            "permissions": sorted(p.key for p in user.user_permissions),
        }
        for f in self.custom_fields:
            snap[f.name] = to_json(getattr(user, f.name, None))
        extra = user.extra or {}
        for ef in self.settings.extra_fields:
            snap[f"extra.{ef.name}"] = extra.get(ef.name)
        return snap

    def _sensitive_fields(self) -> set[str]:
        return {f.name for f in self.custom_fields if f.sensitive} | {
            f"extra.{f.name}" for f in self.settings.extra_fields if f.sensitive
        }

    def _diff(self, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        """{campo: {"old": …, "new": …}} de lo que cambió; los campos sensibles, sin valores."""
        hidden = self._sensitive_fields()
        empty: tuple[Any, ...] = (None, "", [])
        out: dict[str, Any] = {}
        for name in dict.fromkeys([*before, *after]):
            old, new = before.get(name), after.get(name)
            if old == new or (old in empty and new in empty):
                continue
            out[name] = dict(HIDDEN) if name in hidden else {"old": old, "new": new}
        return out

    def _record_change(
        self,
        db: OrmSession,
        action: str,
        user: Any,
        changes: dict[str, Any],
        actor: AuthUser | None,
        reason: str = "",
    ) -> None:
        """Anota un cambio del usuario en la misma transacción que el cambio: o quedan los dos o ninguno."""
        if not self.settings.user_history or not changes:
            return
        db.add(
            self.models.UserChange(
                changed_at=now(),
                user_id=user.id,
                user_repr=str(user.username)[:150],
                action=action,
                changes=changes,
                fields="," + ",".join(changes) + ",",
                actor_id=actor.id if actor and not actor.is_service else None,
                actor_repr=(actor.username if actor else "")[:150],
                reason=(reason or "").strip()[:255],
                ip=request_ip.get()[:64],
            )
        )

    def user_history(
        self,
        user_id: int | None = None,
        *,
        actor_id: int | None = None,
        action: str | None = None,
        field: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Historial de cambios de usuarios, del más reciente al más antiguo.

        Incluye a los usuarios ya eliminados. `field` filtra por campo (`"email"`, `"groups"`,
        `"password"`, `"extra.telefono"`…). Devuelve (registros, total sin paginar).
        """
        if action is not None and action not in HISTORY_ACTIONS:
            raise ValidationError(
                {"action": [f"Acción desconocida: {action}."]},
                hint=f"Use una de: {', '.join(HISTORY_ACTIONS)}.",
                code="invalid_filter",
            )
        H = self.models.UserChange
        stmt = select(H)
        if user_id is not None:
            stmt = stmt.where(H.user_id == user_id)
        if actor_id is not None:
            stmt = stmt.where(H.actor_id == actor_id)
        if action:
            stmt = stmt.where(H.action == action)
        if field:
            # Escapado: un "_" o "%" en el nombre del campo no debe actuar como comodín.
            pattern = "%," + field.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + ",%"
            stmt = stmt.where(H.fields.like(pattern, escape="\\"))
        if since is not None:
            stmt = stmt.where(H.changed_at >= since)
        if until is not None:
            stmt = stmt.where(H.changed_at <= until)
        with self._db(read=True) as db:
            total = db.scalar(select(func.count()).select_from(stmt.subquery()))
            rows = db.scalars(stmt.order_by(H.id.desc()).limit(limit).offset(offset))
            return [
                {
                    "id": h.id,
                    "changed_at": h.changed_at.isoformat(),
                    "user_id": h.user_id,
                    "user": h.user_repr,
                    "action": h.action,
                    "changes": h.changes or {},
                    "actor_id": h.actor_id,
                    "actor": h.actor_repr or "sistema",
                    "reason": h.reason,
                    "ip": h.ip,
                }
                for h in rows
            ], int(total or 0)

    # ================================================================== reglas de privilegio
    # Django deja que cualquier staff con `change_user` se nombre superusuario; aquí no: quien no es
    # superusuario no puede crear ni tocar superusuarios, ni conceder permisos que él mismo no tiene.
    def _check_can_touch(self, actor: AuthUser | None, target: Any) -> None:
        if actor is None or actor.is_superuser:
            return
        if target.is_superuser:
            raise PermissionDeniedError("Solo un superusuario puede modificar a otro superusuario.", code="superuser_required")
        # Quien cambia la contraseña o los datos de alguien podría entrar como esa persona: solo se
        # permite sobre usuarios que no tengan permisos que el administrador no tiene.
        extra = sorted(self._auth_user(target).permissions - actor.permissions)
        if extra and actor.id != target.id:
            raise PermissionDeniedError(
                f"No puede modificar a {target.username}: tiene permisos que usted no tiene ({', '.join(extra)}).",
                code="target_has_more_permissions",
                hint="Pida a un superusuario que haga este cambio.",
            )

    @staticmethod
    def _check_can_grant(actor: AuthUser | None, perms: Iterable[Any]) -> None:
        if actor is None or actor.is_superuser:
            return
        missing = sorted({p.key for p in perms} - actor.permissions)
        if missing:
            raise PermissionDeniedError(f"No puede conceder permisos que usted no tiene: {', '.join(missing)}.")

    def _load_permissions(self, db: OrmSession, ids: Iterable[int]) -> list[Any]:
        ids = list(dict.fromkeys(int(i) for i in ids))
        rows = list(db.scalars(select(self.models.Permission).where(self.models.Permission.id.in_(ids)))) if ids else []
        if len(rows) != len(ids):
            raise ValidationError({"permissions": ["Algún permiso elegido no existe."]})
        return rows

    def _load_groups(self, db: OrmSession, ids: Iterable[int]) -> list[Any]:
        ids = list(dict.fromkeys(int(i) for i in ids))
        rows = list(db.scalars(select(self.models.Group).where(self.models.Group.id.in_(ids)))) if ids else []
        if len(rows) != len(ids):
            raise ValidationError({"groups": ["Algún grupo elegido no existe."]})
        return rows

    def _clean_extra(
        self, extra: dict[str, Any] | None, current: dict[str, Any] | None = None, *, enforce_required: bool = True
    ) -> dict[str, Any]:
        out = dict(current or {})
        errors: dict[str, list[str]] = {}
        for f in self.settings.extra_fields:
            if extra is None or f.name not in extra:
                if enforce_required and f.required and out.get(f.name) in (None, "") and current is None:
                    errors[f"extra.{f.name}"] = ["Este campo es obligatorio."]
                continue
            try:
                out[f.name] = f.clean(extra[f.name])
            except ValueError as exc:
                errors[f"extra.{f.name}"] = [str(exc)]
        if errors:
            raise ValidationError(errors)
        return out

    def _identity(self, username: str | None, email: str | None) -> tuple[str, str]:
        """(username, email) validados según `username_field`."""
        if not self.email_login:
            return validate_username(username or ""), normalize_email(email)
        email = normalize_email(email or username)
        if not email:
            raise ValidationError({"email": ["Este campo es obligatorio: en este sitio se inicia sesión con el correo."]})
        if len(email) > 150:
            raise ValidationError({"email": ["Máximo 150 caracteres."]})
        return email, email

    def _check_email_free(self, db: OrmSession, email: str, exclude: int | None = None) -> None:
        """Con inicio de sesión por correo, dos usuarios no pueden tener el mismo correo."""
        if not self.email_login or not email:
            return
        U = self.models.User
        stmt = select(U.id).where(func.lower(U.email) == email.lower())
        if exclude is not None:
            stmt = stmt.where(U.id != exclude)
        if db.scalar(stmt):
            raise ValidationError({"email": ["Ya existe un usuario con este correo."]}, code="email_taken")

    def _clean_fields(self, values: dict[str, Any], *, creating: bool, enforce_required: bool = True) -> dict[str, Any]:
        """Valida los valores de las columnas propias presentes en `values`."""
        out: dict[str, Any] = {}
        errors: dict[str, list[str]] = {}
        for f in self.custom_fields:
            if f.name not in values:
                if creating and enforce_required and f.required:
                    errors[f.name] = ["Este campo es obligatorio."]
                continue
            if not f.editable:
                continue
            try:
                out[f.name] = f.clean(values[f.name])
            except ValidationError as exc:
                errors.update(exc.errors)
        if errors:
            raise ValidationError(errors)
        return out

    def _superusers_left(self, db: OrmSession, excluding: int) -> int:
        U = self.models.User
        return int(db.scalar(select(func.count()).select_from(U).where(U.is_superuser, U.is_active, U.id != excluding)) or 0)

    # ================================================================== usuarios
    def create_user(
        self,
        username: str,
        password: str | None = None,
        *,
        email: str = "",
        first_name: str = "",
        last_name: str = "",
        is_active: bool = True,
        is_staff: bool = False,
        is_superuser: bool = False,
        groups: Iterable[int] = (),
        permissions: Iterable[int] = (),
        extra: dict[str, Any] | None = None,
        fields: dict[str, Any] | None = None,
        actor: AuthUser | None = None,
        validate: bool = True,
        reason: str = "",
    ) -> dict[str, Any]:
        """Crea un usuario. `password=None` lo deja sin contraseña utilizable (no puede entrar).

        `fields` son los valores de las columnas propias (`user_mixin`); `extra`, los campos JSON.
        `reason` es el motivo que se anota en el historial de cambios.
        """
        U = self.models.User
        username, email = self._identity(username, email)
        if actor is not None and not actor.is_superuser and is_superuser:
            raise PermissionDeniedError("Solo un superusuario puede crear superusuarios.")
        self._check_length(password)
        if password is not None and validate:
            validate_password(
                password,
                min_length=self.settings.password_min_length,
                user_attributes=(username, email, first_name, last_name),
            )
        with self._db() as db:
            self._check_email_free(db, email)
            if db.scalar(select(U.id).where(func.lower(U.username) == username.lower())):
                if self.email_login:
                    raise ValidationError({"email": ["Ya existe un usuario con este correo."]}, code="email_taken")
                raise ValidationError({"username": ["Ya existe un usuario con este nombre."]}, code="username_taken")
            group_rows = self._load_groups(db, groups)
            perm_rows = self._load_permissions(db, permissions)
            self._check_can_grant(actor, [*perm_rows, *(p for g in group_rows for p in g.permissions)])
            user = U(
                username=username,
                password=hashers.make_password(password, self.settings.password_iterations),
                email=email,
                first_name=first_name.strip()[:150],
                last_name=last_name.strip()[:150],
                is_active=is_active,
                is_staff=is_staff,
                is_superuser=is_superuser,
                date_joined=now(),
                # Sin validar (superusuario inicial, comandos) no se exigen los campos extra obligatorios.
                extra=self._clean_extra(extra, enforce_required=validate),
                groups=group_rows,
                user_permissions=perm_rows,
            )
            for name, value in self._clean_fields(fields or {}, creating=True, enforce_required=validate).items():
                setattr(user, name, value)
            db.add(user)
            db.flush()
            self._log(db, actor, "add", "user", user, "Usuario creado.")
            changes = self._diff({}, self._user_snapshot(user))
            if password is not None:
                changes["password"] = dict(HIDDEN)
            self._record_change(db, "create", user, changes, actor, reason)
            db.commit()
            return self._user_dict(user)

    def create_superuser(self, username: str, password: str | None, **fields: Any) -> dict[str, Any]:
        return self.create_user(username, password, is_staff=True, is_superuser=True, **fields)

    def _get_user(self, db: OrmSession, user_id: int) -> Any:
        user = db.get(self.models.User, user_id)
        if user is None:
            raise NotFoundError(f"No existe un usuario con id {user_id}.")
        return user

    def get_user(self, user_id: int) -> dict[str, Any]:
        with self._db(read=True) as db:
            return self._user_dict(self._get_user(db, user_id))

    def get_by_username(self, username: str) -> AuthUser | None:
        U = self.models.User
        with self._db() as db:
            user = db.scalar(select(U).where(func.lower(U.username) == username.strip().lower()))
            return self._auth_user(user) if user else None

    def list_users(
        self,
        *,
        q: str | None = None,
        is_active: bool | None = None,
        is_staff: bool | None = None,
        is_superuser: bool | None = None,
        group_id: int | None = None,
        order: str = "username",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        U = self.models.User
        stmt = select(U)
        if q:
            like = f"%{q.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(U.username).like(like),
                    func.lower(U.email).like(like),
                    func.lower(U.first_name).like(like),
                    func.lower(U.last_name).like(like),
                )
            )
        for column, value in ((U.is_active, is_active), (U.is_staff, is_staff), (U.is_superuser, is_superuser)):
            if value is not None:
                stmt = stmt.where(column == value)
        if group_id is not None:
            stmt = stmt.where(U.groups.any(self.models.Group.id == group_id))
        desc = order.startswith("-")
        column = (
            getattr(U, order.lstrip("-"))
            if order.lstrip("-")
            in {
                "username",
                "email",
                "first_name",
                "last_name",
                "last_login",
                "date_joined",
                "is_staff",
                "is_active",
            }
            else U.username
        )
        with self._db(read=True) as db:
            total = db.scalar(select(func.count()).select_from(stmt.subquery()))
            rows = db.scalars(stmt.order_by(column.desc() if desc else column.asc(), U.id).limit(limit).offset(offset))
            return [self._user_dict(u) for u in rows], int(total or 0)

    def update_user(
        self, user_id: int, changes: dict[str, Any], *, actor: AuthUser | None = None, reason: str = ""
    ) -> dict[str, Any]:
        """Modifica los campos presentes en `changes` (`groups` y `permissions` son listas de ids).

        Lo que cambia queda en el historial (valor anterior y nuevo), con `reason` como motivo.
        """
        U = self.models.User
        with self._db() as db:
            user = self._get_user(db, user_id)
            self._check_can_touch(actor, user)
            before = self._user_snapshot(user)
            changed: list[str] = []
            if self.email_login:
                changes = {k: v for k, v in changes.items() if k != "username"}  # el usuario ES el correo
                if "email" in changes:
                    _, email = self._identity(None, changes.pop("email"))
                    self._check_email_free(db, email, exclude=user.id)
                    clash = db.scalar(select(U.id).where(func.lower(U.username) == email.lower(), U.id != user.id))
                    if clash:
                        raise ValidationError({"email": ["Ya existe un usuario con este correo."]}, code="email_taken")
                    if email != user.email:
                        user.email = user.username = email
                        changed.append("email")
            if "username" in changes:
                username = validate_username(changes["username"])
                clash = db.scalar(select(U.id).where(func.lower(U.username) == username.lower(), U.id != user.id))
                if clash:
                    raise ValidationError({"username": ["Ya existe un usuario con este nombre."]})
                if username != user.username:
                    user.username = username
                    changed.append("username")
            if "email" in changes:
                email = normalize_email(changes["email"])
                if email != user.email:
                    user.email = email
                    changed.append("email")
            for name in ("first_name", "last_name"):
                if name in changes and (value := str(changes[name] or "").strip()[:150]) != getattr(user, name):
                    setattr(user, name, value)
                    changed.append(name)
            for name in ("is_active", "is_staff", "is_superuser"):
                if name in changes and bool(changes[name]) != getattr(user, name):
                    flag = bool(changes[name])
                    if name == "is_superuser" and actor is not None and not actor.is_superuser:
                        raise PermissionDeniedError("Solo un superusuario puede conceder o quitar ese nivel.")
                    if actor is not None and actor.id == user.id and name == "is_active" and not flag:
                        raise ValidationError({"is_active": ["No puede desactivar su propia cuenta."]})
                    losing_super = (
                        user.is_superuser
                        and user.is_active
                        and ((name == "is_superuser" and not flag) or (name == "is_active" and not flag))
                    )
                    if losing_super and self._superusers_left(db, user.id) == 0:
                        raise ValidationError(
                            {name: ["Debe quedar al menos un superusuario activo."]},
                            code="last_superuser",
                            hint="Nombre a otro usuario superusuario antes de quitarle ese nivel.",
                        )
                    setattr(user, name, flag)
                    changed.append(name)
            if "groups" in changes:
                rows = self._load_groups(db, changes["groups"])
                added = [g for g in rows if g not in user.groups]
                self._check_can_grant(actor, [p for g in added for p in g.permissions])
                if {g.id for g in rows} != {g.id for g in user.groups}:
                    user.groups = rows
                    changed.append("groups")
            if "permissions" in changes:
                rows = self._load_permissions(db, changes["permissions"])
                self._check_can_grant(actor, [p for p in rows if p not in user.user_permissions])
                if {p.id for p in rows} != {p.id for p in user.user_permissions}:
                    user.user_permissions = rows
                    changed.append("permissions")
            for name, value in self._clean_fields(changes, creating=False).items():
                if getattr(user, name) != value:
                    setattr(user, name, value)
                    changed.append(name)
            if "extra" in changes:
                extra = self._clean_extra(changes["extra"], user.extra)
                if extra != (user.extra or {}):
                    user.extra = extra
                    changed.append("extra")
            if changed:
                self._log(db, actor, "change", "user", user, f"Modificado: {', '.join(changed)}.")
                self._record_change(db, "update", user, self._diff(before, self._user_snapshot(user)), actor, reason)
                if "is_active" in changed and not user.is_active:
                    db.execute(delete(self.models.Session).where(self.models.Session.user_id == user.id))
                db.commit()
                self._invalidate()
            return self._user_dict(user)

    def delete_user(self, user_id: int, *, actor: AuthUser | None = None, reason: str = "") -> None:
        with self._db() as db:
            user = self._get_user(db, user_id)
            self._check_can_touch(actor, user)
            if actor is not None and actor.id == user.id:
                raise ValidationError(
                    "No puede eliminar su propia cuenta.", code="self_delete", hint="Pida a otro administrador que lo haga."
                )
            if user.is_superuser and user.is_active and self._superusers_left(db, user.id) == 0:
                raise ValidationError(
                    "Debe quedar al menos un superusuario activo.",
                    code="last_superuser",
                    hint="Nombre a otro usuario superusuario antes de quitarle ese nivel o eliminarlo.",
                )
            self._log(db, actor, "delete", "user", user, "Usuario eliminado.")
            # Se guardan los últimos valores: el historial permite saber qué datos tenía.
            self._record_change(db, "delete", user, self._diff(self._user_snapshot(user), {}), actor, reason)
            db.execute(delete(self.models.Session).where(self.models.Session.user_id == user.id))
            db.delete(user)
            db.commit()
        self._invalidate()

    # ================================================================== contraseñas
    def _check_length(self, password: str | None) -> None:
        if password is not None and len(password) > self.settings.password_max_length:
            raise ValidationError({"password": [f"Máximo {self.settings.password_max_length} caracteres."]})

    def set_password(
        self,
        user_id: int,
        password: str | None,
        *,
        actor: AuthUser | None = None,
        keep_session: str | None = None,
        validate: bool = True,
        reason: str = "",
    ) -> None:
        """Cambia la contraseña y cierra las demás sesiones del usuario (como hace Django).

        `password=None` la desactiva (el usuario ya no puede entrar con contraseña).
        """
        S = self.models.Session
        with self._db() as db:
            user = self._get_user(db, user_id)
            if actor is not None and actor.id != user.id:
                self._check_can_touch(actor, user)
            self._check_length(password)
            if password is not None and validate:
                validate_password(
                    password,
                    min_length=self.settings.password_min_length,
                    user_attributes=(user.username, user.email, user.first_name, user.last_name),
                )
            user.password = hashers.make_password(password, self.settings.password_iterations)
            stmt = delete(S).where(S.user_id == user.id)
            if keep_session:
                stmt = stmt.where(S.key_hash != self._hash(keep_session))
            db.execute(stmt)
            self._log(db, actor, "password", "user", user, "Contraseña cambiada.")
            if not reason:
                if password is None:
                    reason = "Contraseña desactivada."
                elif actor is None:
                    reason = ""
                elif actor.id == user.id:
                    reason = "Cambiada por el propio usuario."
                else:
                    reason = "Asignada por un administrador."
            self._record_change(db, "password", user, {"password": dict(HIDDEN)}, actor, reason)
            db.commit()
        self._invalidate()

    def change_password(self, user: AuthUser, old_password: str, new_password: str, *, keep_session: str | None = None) -> None:
        """El propio usuario cambia su contraseña: debe conocer la actual."""
        with self._db() as db:
            row = self._get_user(db, user.id)
            if not hashers.check_password(old_password, row.password):
                raise ValidationError({"old_password": ["La contraseña actual no es correcta."]})
        self.set_password(user.id, new_password, actor=user, keep_session=keep_session)

    # --- restablecimiento: mismo esquema que PasswordResetTokenGenerator de Django ---
    def _reset_hash(self, user: Any, ts: int) -> str:
        login = user.last_login.replace(microsecond=0).isoformat() if user.last_login else ""
        value = f"{user.id}{user.password}{login}{ts}{user.email}"
        return hmac.new(self.secret.encode(), value.encode(), hashlib.sha256).hexdigest()[::2]

    def make_reset_token(self, user_id: int, *, actor: AuthUser | None = None) -> str:
        """Token de un solo uso: deja de valer al cambiar la contraseña, al iniciar sesión o al caducar."""
        with self._db() as db:
            user = self._get_user(db, user_id)
            if actor is not None:
                self._check_can_touch(actor, user)
                self._log(db, actor, "reset_link", "user", user, "Enlace de restablecimiento generado.")
                db.commit()
            ts = int(time.time())
            return f"{ts:x}-{self._reset_hash(user, ts)}"

    def reset_password(self, user_id: int, token: str, new_password: str) -> None:
        invalid = ValidationError(
            "El enlace para restablecer la contraseña no es válido, ya se usó o caducó.",
            code="invalid_reset_link",
            hint="Pida a un administrador un enlace nuevo. Cada enlace sirve una sola vez.",
        )
        with self._db() as db:
            user = db.get(self.models.User, user_id)
            try:
                ts_text, digest = token.split("-", 1)
                ts = int(ts_text, 16)
            except ValueError:
                raise invalid from None
            if user is None or not user.is_active or not hmac.compare_digest(self._reset_hash(user, ts), digest):
                raise invalid
            if time.time() - ts > self.settings.password_reset_timeout:
                raise invalid
        self.set_password(user_id, new_password, reason="Restablecida con un enlace.")

    # ================================================================== inicio de sesión
    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _throttle(self, key: tuple[str, str]) -> None:
        window = self.settings.login_lockout_seconds
        attempts = self._failures.get(key)
        if not attempts:
            return
        cutoff = time.monotonic() - window
        while attempts and attempts[0] < cutoff:
            attempts.popleft()
        if len(attempts) >= self.settings.login_max_failures:
            raise TooManyAttemptsError(int(window - (time.monotonic() - attempts[0])))

    def authenticate(
        self, username: str | None = None, password: str | None = None, *, ip: str = "", user_agent: str = "", **credentials: Any
    ) -> AuthUser:
        """Prueba cada backend en orden (como `django.contrib.auth.authenticate`).

        Lanza `InvalidCredentialsError` si ninguno acepta las credenciales, `TooManyAttemptsError` tras
        demasiados intentos fallidos y `PermissionDeniedError` si un backend niega el acceso.
        """
        if len(password or "") > self.settings.password_max_length:
            raise InvalidCredentialsError()
        key = ((username or "").strip().lower()[:150], ip)
        self._throttle(key)
        if len(self._failures) > 10_000:  # un atacante que rota usuarios no debe llenar la memoria
            self._failures.clear()
        request = AuthRequest(ip=ip, user_agent=user_agent)
        given = {"username": username, "password": password, **credentials}
        given = {k: v for k, v in given.items() if v is not None}
        for path, backend in self.backends:
            try:
                inspect_signature(backend.authenticate).bind(request, **given)
            except TypeError:
                continue  # este backend no acepta estas credenciales
            try:
                row = backend.authenticate(request, **given)
            except PermissionDeniedError:
                # Igual que en Django: un backend que niega el acceso detiene la búsqueda.
                self._record_failure(key)
                raise
            except Exception:  # noqa: BLE001 - un backend caído (LDAP sin red) no debe impedir los demás
                logger.exception("djauth: el backend %s falló al autenticar; se prueba el siguiente", path)
                continue
            if row is not None:
                self._failures.pop(key, None)
                return self._auth_user(row, backend=path)
        self._record_failure(key)
        raise InvalidCredentialsError()

    def _record_failure(self, key: tuple[str, str]) -> None:
        self._failures.setdefault(key, deque(maxlen=self.settings.login_max_failures * 2)).append(time.monotonic())

    # ------------------------------------------------------------------ ayudas para backends
    def find_user_row(self, username: str) -> Any:
        """Fila del usuario por el campo de inicio de sesión (`username_field`), sin distinguir
        mayúsculas, o None."""
        U = self.models.User
        column = U.email if self.email_login else U.username
        value = (username or "").strip().lower()
        if not value:
            return None
        with self._db() as db:
            return db.scalar(select(U).where(func.lower(column) == value).order_by(U.id).limit(1))

    def get_user_row(self, user_id: int) -> Any:
        with self._db() as db:
            return db.get(self.models.User, user_id)

    def rehash_password(self, user_id: int, password: str) -> None:
        """Vuelve a cifrar la contraseña con las iteraciones actuales (al subirlas en la configuración)."""
        with self._db() as db:
            user = self._get_user(db, user_id)
            user.password = hashers.make_password(password, self.settings.password_iterations)
            db.commit()

    def get_or_create_user(self, username: str, *, defaults: dict[str, Any] | None = None, update: bool = True) -> Any:
        """Para backends externos (LDAP, otro sistema): devuelve la copia local del usuario y la crea si
        no existe, sin contraseña utilizable (solo puede entrar por ese backend).

        `defaults` acepta email, first_name, last_name, is_staff, is_active, `fields` y `extra`. Con
        `update=True`, se actualizan los datos de un usuario existente en cada inicio de sesión.
        """
        defaults = dict(defaults or {})
        row = self.find_user_row(username)
        if row is None:
            self.create_user(username, None, validate=False, reason="Creado por un backend de autenticación.", **defaults)
        elif update:
            changes = {k: v for k, v in defaults.items() if k in ("email", "first_name", "last_name", "extra")}
            changes.update(defaults.get("fields") or {})
            if changes:
                self.update_user(row.id, changes, reason="Sincronizado desde un backend de autenticación.")
        return self.find_user_row(username)

    def login(self, user: AuthUser, *, kind: str = "session", ip: str = "", user_agent: str = "") -> str:
        """Abre una sesión (`kind="session"`, cookie) o emite un token (`kind="bearer"`).

        Devuelve el token en claro una única vez; en la base solo se guarda su hash SHA-256, de modo
        que una copia de la base de datos no sirve para suplantar a nadie.
        """
        if kind not in ("session", "bearer"):
            raise ValueError("kind debe ser 'session' o 'bearer'")
        age = self.settings.session_cookie_age if kind == "session" else self.settings.bearer_token_age
        token = secrets.token_urlsafe(32)
        S = self.models.Session
        with self._db() as db:
            row = self._get_user(db, user.id)
            row.last_login = now()
            db.execute(delete(S).where(S.expires < now()))  # limpieza de sesiones caducadas
            db.add(
                S(
                    key_hash=self._hash(token),
                    user_id=user.id,
                    kind=kind,
                    backend=user.backend or self.backends[0][0],
                    created=now(),
                    expires=now() + timedelta(seconds=age),
                    ip=ip[:64],
                    user_agent=user_agent[:255],
                )
            )
            what = "Inicio de sesión" if kind == "session" else "Token emitido"
            self._log(db, user, "login", "user", row, f"{what} desde {ip or 'origen desconocido'}.")
            db.commit()
        return token

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self._db() as db:
            db.execute(delete(self.models.Session).where(self.models.Session.key_hash == self._hash(token)))
            db.commit()
        self._invalidate()

    def logout_all(self, user_id: int, *, actor: AuthUser | None = None) -> None:
        """Cierra todas las sesiones de un usuario."""
        with self._db() as db:
            user = self._get_user(db, user_id)
            self._check_can_touch(actor, user)
            db.execute(delete(self.models.Session).where(self.models.Session.user_id == user_id))
            self._log(db, actor, "logout_all", "user", user, "Sesiones cerradas.")
            db.commit()
        self._invalidate()

    def user_from_token(self, token: str | None, kind: str = "session") -> AuthUser | None:
        """Usuario de una sesión o token vigente del tipo indicado, o None.

        Un token bearer no vale como cookie ni al revés. Caché de 5 s para no consultar la base en
        cada petición; cualquier cambio de usuarios, permisos o sesiones la vacía.
        """
        if not token or len(token) > 200:
            return None
        key = f"{kind}:{self._hash(token)}"
        with self._cache_lock:
            hit = self._cache.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]
        S = self.models.Session
        with self._db() as db:
            session = db.get(S, key.split(":", 1)[1])
            if session is None or session.kind != kind or session.expires < now():
                return None
            backend_path = session.backend or self.backends[0][0]
        # Como en Django: la sesión pertenece al backend que autenticó; si ya no está configurado, no vale.
        backend = dict(self.backends).get(backend_path)
        if backend is None:
            return None
        user = backend.get_user(session.user_id)
        if user is None:
            return None
        auth_user = self._auth_user(user, backend=backend_path)
        with self._cache_lock:
            if len(self._cache) > 5000:
                self._cache.clear()
            self._cache[key] = (time.monotonic() + 5.0, auth_user)
        return auth_user

    def count_sessions(self, user_id: int) -> int:
        S = self.models.Session
        with self._db(read=True) as db:
            return int(db.scalar(select(func.count()).select_from(S).where(S.user_id == user_id, S.expires >= now())) or 0)

    # ================================================================== grupos (roles)
    def list_groups(self) -> list[dict[str, Any]]:
        G, U = self.models.Group, self.models.User
        with self._db(read=True) as db:
            out = []
            for g in db.scalars(select(G).order_by(G.name)):
                members = db.scalar(select(func.count()).select_from(U).where(U.groups.any(G.id == g.id)))
                out.append(self._group_dict(g, int(members or 0)))
            return out

    def _get_group(self, db: OrmSession, group_id: int) -> Any:
        group = db.get(self.models.Group, group_id)
        if group is None:
            raise NotFoundError(f"No existe un grupo con id {group_id}.")
        return group

    def get_group(self, group_id: int) -> dict[str, Any]:
        with self._db(read=True) as db:
            return self._group_dict(self._get_group(db, group_id))

    def _group_name(self, db: OrmSession, name: str, exclude: int | None = None) -> str:
        G = self.models.Group
        name = (name or "").strip()
        if not name:
            raise ValidationError({"name": ["Este campo es obligatorio."]})
        if len(name) > 150:
            raise ValidationError({"name": ["Máximo 150 caracteres."]})
        stmt = select(G.id).where(func.lower(G.name) == name.lower())
        if exclude is not None:
            stmt = stmt.where(G.id != exclude)
        if db.scalar(stmt):
            raise ValidationError({"name": ["Ya existe un grupo con este nombre."]})
        return name

    def create_group(self, name: str, permissions: Iterable[int] = (), *, actor: AuthUser | None = None) -> dict[str, Any]:
        with self._db() as db:
            rows = self._load_permissions(db, permissions)
            self._check_can_grant(actor, rows)
            group = self.models.Group(name=self._group_name(db, name), permissions=rows)
            db.add(group)
            db.flush()
            self._log(db, actor, "add", "group", group, "Grupo creado.")
            db.commit()
            return self._group_dict(group)

    def update_group(self, group_id: int, changes: dict[str, Any], *, actor: AuthUser | None = None) -> dict[str, Any]:
        with self._db() as db:
            group = self._get_group(db, group_id)
            changed = []
            if "name" in changes and changes["name"] != group.name:
                group.name = self._group_name(db, changes["name"], exclude=group.id)
                changed.append("name")
            if "permissions" in changes:
                rows = self._load_permissions(db, changes["permissions"])
                self._check_can_grant(actor, [p for p in rows if p not in group.permissions])
                if {p.id for p in rows} != {p.id for p in group.permissions}:
                    group.permissions = rows
                    changed.append("permissions")
            if changed:
                self._log(db, actor, "change", "group", group, f"Modificado: {', '.join(changed)}.")
                db.commit()
                self._invalidate()
            return self._group_dict(group)

    def delete_group(self, group_id: int, *, actor: AuthUser | None = None) -> None:
        with self._db() as db:
            group = self._get_group(db, group_id)
            self._log(db, actor, "delete", "group", group, "Grupo eliminado.")
            # Los miembros pierden el grupo: es un cambio de cada usuario y queda en su historial.
            U = self.models.User
            for user in db.scalars(select(U).where(U.groups.any(self.models.Group.id == group.id))):
                names = sorted(g.name for g in user.groups)
                remaining = [n for n in names if n != group.name]
                self._record_change(
                    db, "update", user, {"groups": {"old": names, "new": remaining}}, actor, f"Se eliminó el grupo {group.name}."
                )
            # Se borran a mano las filas intermedias: así no depende de que el motor aplique ON DELETE
            # CASCADE (SQLite sin claves foráneas activas, MyISAM) ni de que el id no se reutilice.
            db.execute(delete(U.groups.property.secondary).where(U.groups.property.secondary.c.group_id == group.id))
            db.delete(group)
            db.commit()
        self._invalidate()

    def ensure_group(self, name: str, permissions: Iterable[str]) -> bool:
        """Crea un rol con esos permisos (`app.codename`) solo si no existe. No pisa los ya ajustados
        desde la administración. Devuelve True si lo creó."""
        G, P = self.models.Group, self.models.Permission
        wanted = set(permissions)
        with self._db() as db:
            if db.scalar(select(G.id).where(func.lower(G.name) == name.lower())):
                return False
            rows = [p for p in db.scalars(select(P)) if p.key in wanted]
            unknown = wanted - {p.key for p in rows}
            if unknown:
                raise ValueError(f"Permisos no declarados: {', '.join(sorted(unknown))}")
            db.add(G(name=name, permissions=rows))
            db.commit()
        return True

    # ================================================================== permisos y registro
    def list_permissions(self) -> list[dict[str, Any]]:
        """Todos los permisos. `declared` indica si lo declara el código (no se modifica desde la API)."""
        P = self.models.Permission
        with self._db(read=True) as db:
            return [self._permission_dict(p) for p in db.scalars(select(P).order_by(P.app_label, P.codename))]

    def _permission_dict(self, p: Any) -> dict[str, Any]:
        return {
            "id": p.id,
            "app_label": p.app_label,
            "codename": p.codename,
            "name": p.name,
            "key": p.key,
            "declared": self._is_declared(p.app_label, p.codename),
        }

    def _is_declared(self, app_label: str, codename: str) -> bool:
        """Lo declara el código (permisos de djauth, `AuthSettings.permissions` o `register_permissions`)."""
        return codename in self._registry.get(app_label, {})

    def _get_permission(self, db: OrmSession, permission_id: int) -> Any:
        perm = db.get(self.models.Permission, permission_id)
        if perm is None:
            raise NotFoundError(f"No existe un permiso con id {permission_id}.")
        return perm

    def get_permission(self, permission_id: int) -> dict[str, Any]:
        with self._db(read=True) as db:
            return self._permission_dict(self._get_permission(db, permission_id))

    @staticmethod
    def _permission_name(name: str) -> str:
        name = (name or "").strip()
        if not name:
            raise ValidationError({"name": ["Este campo es obligatorio."]})
        if len(name) > 255:
            raise ValidationError({"name": ["Máximo 255 caracteres."]})
        return name

    def _check_editable(self, perm: Any) -> None:
        if self._is_declared(perm.app_label, perm.codename):
            raise PermissionDeniedError(
                f"El permiso {perm.key} lo declara el código: se cambia allí, no desde la administración.",
                code="declared_permission",
                hint="Al arrancar, la aplicación vuelve a crear los permisos declarados con su descripción.",
            )

    def create_permission(self, app_label: str, codename: str, name: str, *, actor: AuthUser | None = None) -> dict[str, Any]:
        """Crea un permiso propio (`app_label.codename`), como agregar un `Permission` en Django.

        No se concede a nadie: se asigna luego a grupos o usuarios, y solo puede asignarlo quien ya lo
        tiene (o un superusuario). Las aplicaciones de djauth (`auth`, `sessions`, `admin`) están reservadas.
        """
        app_label, codename = (app_label or "").strip(), (codename or "").strip()
        errors: dict[str, list[str]] = {}
        for field_name, value in (("app_label", app_label), ("codename", codename)):
            if not PERMISSION_PART.match(value):
                errors[field_name] = ["Use minúsculas, números y guion bajo, empezando por una letra (máximo 100 caracteres)."]
        if "app_label" not in errors and app_label in RESERVED_APP_LABELS:
            errors["app_label"] = [f"La aplicación {app_label!r} está reservada para djauth."]
        try:
            name = self._permission_name(name)
        except ValidationError as exc:
            errors.update(exc.errors)
        if errors:
            raise ValidationError(errors)
        P = self.models.Permission
        with self._db() as db:
            if db.scalar(select(P.id).where(P.app_label == app_label, P.codename == codename)):
                raise ValidationError({"codename": [f"Ya existe el permiso {app_label}.{codename}."]})
            perm = P(app_label=app_label, codename=codename, name=name)
            db.add(perm)
            db.flush()
            self._log(db, actor, "add", "permission", perm, f"Permiso {perm.key} creado.")
            db.commit()
            return self._permission_dict(perm)

    def update_permission(self, permission_id: int, changes: dict[str, Any], *, actor: AuthUser | None = None) -> dict[str, Any]:
        """Cambia la descripción (`name`) de un permiso propio. El código (`app_label.codename`) no
        cambia: las rutas lo usan por ese nombre; para otro código, cree un permiso nuevo."""
        with self._db() as db:
            perm = self._get_permission(db, permission_id)
            self._check_editable(perm)
            if "name" in changes:
                name = self._permission_name(changes["name"])
                if name != perm.name:
                    perm.name = name
                    self._log(db, actor, "change", "permission", perm, f"Permiso {perm.key}: modificado name.")
                    db.commit()
            return self._permission_dict(perm)

    def delete_permission(self, permission_id: int, *, actor: AuthUser | None = None) -> None:
        """Elimina un permiso propio. Los grupos y usuarios que lo tenían lo pierden; el cambio queda en
        el historial de cada usuario afectado."""
        G, U = self.models.Group, self.models.User
        with self._db() as db:
            perm = self._get_permission(db, permission_id)
            self._check_editable(perm)
            groups = sorted(g.name for g in db.scalars(select(G).where(G.permissions.any(id=perm.id))))
            for user in db.scalars(select(U).where(U.user_permissions.any(id=perm.id))):
                keys = sorted(p.key for p in user.user_permissions)
                self._record_change(
                    db,
                    "update",
                    user,
                    {"permissions": {"old": keys, "new": [k for k in keys if k != perm.key]}},
                    actor,
                    f"Se eliminó el permiso {perm.key}.",
                )
            detail = f" Lo tenían los grupos: {', '.join(groups)}." if groups else ""
            self._log(db, actor, "delete", "permission", perm, f"Permiso {perm.key} eliminado.{detail}")
            for table in (G.permissions.property.secondary, U.user_permissions.property.secondary):
                db.execute(delete(table).where(table.c.permission_id == perm.id))
            db.delete(perm)
            db.commit()
        self._invalidate()

    def list_log(
        self, *, limit: int = 100, offset: int = 0, object_type: str | None = None, object_id: str | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        L = self.models.LogEntry
        stmt = select(L)
        if object_type:
            stmt = stmt.where(L.object_type == object_type)
        if object_id:
            stmt = stmt.where(L.object_id == str(object_id))
        with self._db(read=True) as db:
            total = db.scalar(select(func.count()).select_from(stmt.subquery()))
            rows = db.scalars(stmt.order_by(L.id.desc()).limit(limit).offset(offset))
            return [
                {
                    "id": e.id,
                    "action_time": e.action_time.isoformat(),
                    "username": e.username,
                    "action": e.action,
                    "object_type": e.object_type,
                    "object_id": e.object_id,
                    "object_repr": e.object_repr,
                    "message": e.message,
                }
                for e in rows
            ], int(total or 0)

    # ================================================================== integración con FastAPI
    def install(self, app: Any, **options: Any) -> AuthKit:
        """Conecta el módulo a una aplicación FastAPI (rutas, páginas y protección). Ver `djauth.api`."""
        from djauth.api import install

        install(self, app, **options)
        return self
