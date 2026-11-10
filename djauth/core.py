"""Núcleo del módulo: usuarios, grupos (roles), permisos, sesiones y registro de acciones.

No depende de FastAPI: se puede usar desde un script, una tarea o cualquier framework. Las funciones
devuelven datos simples (`AuthUser`, diccionarios), nunca objetos del ORM.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import deque
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, delete, func, or_, select
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from djauth import hashers
from djauth.errors import (
    InvalidCredentialsError,
    NotFoundError,
    PermissionDeniedError,
    TooManyAttemptsError,
    ValidationError,
)
from djauth.models import build_models
from djauth.settings import AuthSettings
from djauth.validators import normalize_email, validate_password, validate_username

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
        "view_logentry": "Puede ver el registro de acciones",
    }
}


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
        }


SERVICE_USER = AuthUser(id=0, username="api-key", is_superuser=True, is_service=True)


class AuthKit:
    def __init__(self, settings: AuthSettings | None = None) -> None:
        self.settings = settings or AuthSettings()
        self.models = build_models(self.settings.table_prefix)
        url = self.settings.database_url
        kwargs: dict[str, Any] = {}
        if url.startswith("sqlite:///") and ":memory:" not in url and len(url) > len("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if ":memory:" in url or url in ("sqlite://", "sqlite:///"):
                kwargs["poolclass"] = StaticPool  # una sola conexión: la base en memoria no se pierde
        self.engine = create_engine(url, **kwargs)
        self._session_factory = sessionmaker(self.engine, expire_on_commit=False)
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
        self.models.Base.metadata.create_all(self.engine)
        self._initialized = True
        self._sync_permissions()
        boot = self.settings.bootstrap_superuser
        if boot and boot[0] and boot[1]:
            with self._db() as db:
                empty = db.scalar(select(func.count()).select_from(self.models.User)) == 0
            if empty:
                self.create_superuser(boot[0], boot[1], email=boot[2] if len(boot) > 2 else "", validate=False)
        return self

    @contextmanager
    def _db(self):
        with self._session_factory() as db:
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
    def _auth_user(self, u: Any) -> AuthUser:
        perms = {p.key for p in u.user_permissions} | {p.key for g in u.groups for p in g.permissions}
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
                object_repr=str(getattr(obj, "username", None) or getattr(obj, "name", None) or "")[:200],
                message=message[:2000],
            )
        )

    # ================================================================== reglas de privilegio
    # Django deja que cualquier staff con `change_user` se nombre superusuario; aquí no: quien no es
    # superusuario no puede crear ni tocar superusuarios, ni conceder permisos que él mismo no tiene.
    @staticmethod
    def _check_can_touch(actor: AuthUser | None, target: Any) -> None:
        if actor is not None and not actor.is_superuser and target.is_superuser:
            raise PermissionDeniedError("Solo un superusuario puede modificar a otro superusuario.")

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

    def _superusers_left(self, db: OrmSession, excluding: int) -> int:
        U = self.models.User
        return db.scalar(select(func.count()).select_from(U).where(U.is_superuser, U.is_active, U.id != excluding))

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
        actor: AuthUser | None = None,
        validate: bool = True,
    ) -> dict[str, Any]:
        """Crea un usuario. `password=None` lo deja sin contraseña utilizable (no puede entrar)."""
        U = self.models.User
        username = validate_username(username)
        email = normalize_email(email)
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
            if db.scalar(select(U.id).where(func.lower(U.username) == username.lower())):
                raise ValidationError({"username": ["Ya existe un usuario con este nombre."]})
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
            db.add(user)
            db.flush()
            self._log(db, actor, "add", "user", user, "Usuario creado.")
            db.commit()
            return self._user_dict(user)

    def create_superuser(self, username: str, password: str | None, **fields: Any) -> dict[str, Any]:
        return self.create_user(username, password, is_staff=True, is_superuser=True, **fields)

    def _get_user(self, db: OrmSession, user_id: int) -> Any:
        user = db.get(self.models.User, user_id)
        if user is None:
            raise NotFoundError("El usuario no existe.")
        return user

    def get_user(self, user_id: int) -> dict[str, Any]:
        with self._db() as db:
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
            getattr(U, order.lstrip("-"), None)
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
        with self._db() as db:
            total = db.scalar(select(func.count()).select_from(stmt.subquery()))
            rows = db.scalars(stmt.order_by(column.desc() if desc else column.asc(), U.id).limit(limit).offset(offset))
            return [self._user_dict(u) for u in rows], int(total or 0)

    def update_user(self, user_id: int, changes: dict[str, Any], *, actor: AuthUser | None = None) -> dict[str, Any]:
        """Modifica los campos presentes en `changes` (`groups` y `permissions` son listas de ids)."""
        U = self.models.User
        with self._db() as db:
            user = self._get_user(db, user_id)
            self._check_can_touch(actor, user)
            changed: list[str] = []
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
                    value = bool(changes[name])
                    if name == "is_superuser" and actor is not None and not actor.is_superuser:
                        raise PermissionDeniedError("Solo un superusuario puede conceder o quitar ese nivel.")
                    if actor is not None and actor.id == user.id and name == "is_active" and not value:
                        raise ValidationError({"is_active": ["No puede desactivar su propia cuenta."]})
                    losing_super = (
                        user.is_superuser
                        and user.is_active
                        and ((name == "is_superuser" and not value) or (name == "is_active" and not value))
                    )
                    if losing_super and self._superusers_left(db, user.id) == 0:
                        raise ValidationError({name: ["Debe quedar al menos un superusuario activo."]})
                    setattr(user, name, value)
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
            if "extra" in changes:
                extra = self._clean_extra(changes["extra"], user.extra)
                if extra != (user.extra or {}):
                    user.extra = extra
                    changed.append("extra")
            if changed:
                self._log(db, actor, "change", "user", user, f"Modificado: {', '.join(changed)}.")
                if "is_active" in changed and not user.is_active:
                    db.execute(delete(self.models.Session).where(self.models.Session.user_id == user.id))
                db.commit()
                self._invalidate()
            return self._user_dict(user)

    def delete_user(self, user_id: int, *, actor: AuthUser | None = None) -> None:
        with self._db() as db:
            user = self._get_user(db, user_id)
            self._check_can_touch(actor, user)
            if actor is not None and actor.id == user.id:
                raise ValidationError("No puede eliminar su propia cuenta.")
            if user.is_superuser and user.is_active and self._superusers_left(db, user.id) == 0:
                raise ValidationError("Debe quedar al menos un superusuario activo.")
            self._log(db, actor, "delete", "user", user, "Usuario eliminado.")
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
    ) -> None:
        """Cambia la contraseña y cierra las demás sesiones del usuario (como hace Django)."""
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
        invalid = ValidationError("El enlace no es válido o ya caducó. Pida uno nuevo al administrador.")
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
        self.set_password(user_id, new_password)

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

    def authenticate(self, username: str, password: str, *, ip: str = "") -> AuthUser:
        """Valida usuario y contraseña. Lanza `InvalidCredentialsError` o `TooManyAttemptsError`."""
        U = self.models.User
        if len(password or "") > self.settings.password_max_length:
            raise InvalidCredentialsError("Usuario o contraseña incorrectos.")
        key = ((username or "").strip().lower()[:150], ip)
        self._throttle(key)
        if len(self._failures) > 10_000:  # un atacante que rota usuarios no debe llenar la memoria
            self._failures.clear()
        with self._db() as db:
            user = db.scalar(select(U).where(func.lower(U.username) == key[0]))
            if user is None:
                # Mismo coste que con un usuario real: el tiempo de respuesta no revela si existe.
                hashers.make_password(password, self.settings.password_iterations)
                ok = False
            else:
                ok = hashers.check_password(password, user.password) and user.is_active
            if not ok:
                self._failures.setdefault(key, deque(maxlen=self.settings.login_max_failures * 2)).append(time.monotonic())
                raise InvalidCredentialsError("Usuario o contraseña incorrectos.")
            self._failures.pop(key, None)
            if hashers.must_update(user.password, self.settings.password_iterations):
                user.password = hashers.make_password(password, self.settings.password_iterations)
                db.commit()
            return self._auth_user(user)

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
            user = db.get(self.models.User, session.user_id)
            if user is None or not user.is_active:
                return None
            auth_user = self._auth_user(user)
        with self._cache_lock:
            if len(self._cache) > 5000:
                self._cache.clear()
            self._cache[key] = (time.monotonic() + 5.0, auth_user)
        return auth_user

    def count_sessions(self, user_id: int) -> int:
        S = self.models.Session
        with self._db() as db:
            return int(db.scalar(select(func.count()).select_from(S).where(S.user_id == user_id, S.expires >= now())) or 0)

    # ================================================================== grupos (roles)
    def list_groups(self) -> list[dict[str, Any]]:
        G, U = self.models.Group, self.models.User
        with self._db() as db:
            out = []
            for g in db.scalars(select(G).order_by(G.name)):
                members = db.scalar(select(func.count()).select_from(U).where(U.groups.any(G.id == g.id)))
                out.append(self._group_dict(g, int(members or 0)))
            return out

    def _get_group(self, db: OrmSession, group_id: int) -> Any:
        group = db.get(self.models.Group, group_id)
        if group is None:
            raise NotFoundError("El grupo no existe.")
        return group

    def get_group(self, group_id: int) -> dict[str, Any]:
        with self._db() as db:
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
        P = self.models.Permission
        with self._db() as db:
            return [
                {"id": p.id, "app_label": p.app_label, "codename": p.codename, "name": p.name, "key": p.key}
                for p in db.scalars(select(P).order_by(P.app_label, P.codename))
            ]

    def list_log(
        self, *, limit: int = 100, offset: int = 0, object_type: str | None = None, object_id: str | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        L = self.models.LogEntry
        stmt = select(L)
        if object_type:
            stmt = stmt.where(L.object_type == object_type)
        if object_id:
            stmt = stmt.where(L.object_id == str(object_id))
        with self._db() as db:
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
