"""Backends de autenticación, el equivalente de `AUTHENTICATION_BACKENDS` de Django.

    AuthSettings(authentication_backends=(
        "miapp.auth.LDAPBackend",            # primero se intenta contra el directorio de la empresa
        "djauth.backends.ModelBackend",      # si no, usuario y contraseña de la base local
    ))

Igual que en Django:

- **Autenticar:** se prueba cada backend en orden; el primero que devuelve un usuario gana. Si uno
  lanza `PermissionDeniedError`, se detiene la búsqueda y el acceso se niega. Un backend cuyo
  `authenticate` no acepta las credenciales recibidas se salta.
- **Sesión:** la sesión recuerda qué backend autenticó al usuario y en cada petición le pide el
  usuario con `get_user()`. Si ese backend se quita de la configuración, sus sesiones dejan de valer.
- **Permisos:** `user.has_perm()` suma los permisos que dan todos los backends (`get_all_permissions`).

Diferencias: los backends reciben y devuelven filas de usuario de la base (`kit.models.User`), y un
backend externo (LDAP, otro sistema) crea o actualiza la copia local con `kit.get_or_create_user()`;
así los grupos, permisos y la administración funcionan igual para todos los usuarios.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from djauth import hashers

if TYPE_CHECKING:
    from djauth.core import AuthKit


@dataclass(frozen=True)
class AuthRequest:
    """Datos de la petición de inicio de sesión que reciben los backends (el `request` de Django)."""

    ip: str = ""
    user_agent: str = ""
    headers: dict[str, str] = field(default_factory=dict)


class BaseBackend:
    """Base de un backend. Sobrescriba lo que necesite; lo que no, no aporta nada.

    `self.kit` es la instancia de `AuthKit` que lo usa (se asigna al cargarlo).
    """

    kit: AuthKit

    def authenticate(
        self, request: AuthRequest, username: str | None = None, password: str | None = None, **credentials: Any
    ) -> Any:
        """Devuelve la fila del usuario si las credenciales son válidas, o None."""
        return None

    def get_user(self, user_id: int) -> Any:
        """Fila del usuario de una sesión abierta con este backend, o None para cerrarla."""
        return None

    def get_user_permissions(self, user_obj: Any) -> set[str]:
        return set()

    def get_group_permissions(self, user_obj: Any) -> set[str]:
        return set()

    def get_all_permissions(self, user_obj: Any) -> set[str]:
        return {*self.get_user_permissions(user_obj), *self.get_group_permissions(user_obj)}


class ModelBackend(BaseBackend):
    """Usuario y contraseña de la base de datos, con los grupos y permisos de la administración.
    Rechaza a los usuarios inactivos (como `django.contrib.auth.backends.ModelBackend`)."""

    def authenticate(
        self, request: AuthRequest, username: str | None = None, password: str | None = None, **credentials: Any
    ) -> Any:
        if username is None or password is None:
            return None
        user = self.kit.find_user_row(username)
        if user is None:
            # Mismo coste que con un usuario real: el tiempo de respuesta no revela si existe.
            hashers.make_password(password, self.kit.settings.password_iterations)
            return None
        if hashers.check_password(password, user.password) and self.user_can_authenticate(user):
            if hashers.must_update(user.password, self.kit.settings.password_iterations):
                self.kit.rehash_password(user.id, password)
            return user
        return None

    def user_can_authenticate(self, user_obj: Any) -> bool:
        return bool(getattr(user_obj, "is_active", False))

    def get_user(self, user_id: int) -> Any:
        user = self.kit.get_user_row(user_id)
        return user if user is not None and self.user_can_authenticate(user) else None

    def get_user_permissions(self, user_obj: Any) -> set[str]:
        if not user_obj.is_active:
            return set()
        return {p.key for p in user_obj.user_permissions}

    def get_group_permissions(self, user_obj: Any) -> set[str]:
        if not user_obj.is_active:
            return set()
        return {p.key for g in user_obj.groups for p in g.permissions}


class AllowAllUsersModelBackend(ModelBackend):
    """Como `ModelBackend`, pero deja entrar también a los usuarios inactivos (igual que en Django).
    Útil si "inactivo" significa otra cosa en su proyecto; casi nunca es lo que se quiere."""

    def user_can_authenticate(self, user_obj: Any) -> bool:
        return True


def load_backend(path: str | type | BaseBackend) -> tuple[str, BaseBackend]:
    """Acepta una ruta (`"paquete.modulo.Clase"`), una clase o una instancia. Devuelve (ruta, instancia)."""
    if isinstance(path, str):
        module_name, _, class_name = path.rpartition(".")
        if not module_name:
            raise ValueError(f"Ruta de backend no válida: {path!r} (use 'paquete.modulo.Clase')")
        try:
            cls = getattr(importlib.import_module(module_name), class_name)
        except (ImportError, AttributeError) as exc:
            raise ValueError(f"No se pudo cargar el backend {path!r}: {exc}") from exc
        return path, cls()
    if isinstance(path, type):
        return f"{path.__module__}.{path.__qualname__}", path()
    return f"{type(path).__module__}.{type(path).__qualname__}", path
