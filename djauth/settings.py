"""Configuración del módulo. Todo lo que un proyecto suele querer cambiar está aquí."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExtraField:
    """Campo adicional del usuario (el equivalente a ampliar el modelo de usuario en Django).

    Se guarda en la columna JSON `extra` y aparece en el formulario de administración.
    """

    name: str
    label: str
    type: str = "text"  # text | number | bool | choice
    choices: tuple[str, ...] = ()
    required: bool = False
    help_text: str = ""
    # True: el historial de cambios registra que cambió, pero no los valores (datos personales).
    sensitive: bool = False

    def clean(self, value: Any) -> Any:
        if value in (None, ""):
            if self.required:
                raise ValueError("Este campo es obligatorio.")
            return None
        if self.type == "bool":
            return bool(value)
        if self.type == "number":
            try:
                return float(value) if "." in str(value) else int(value)
            except (TypeError, ValueError):
                raise ValueError("Escriba un número.") from None
        value = str(value).strip()
        if self.type == "choice" and value not in self.choices:
            raise ValueError(f"Elija una de: {', '.join(self.choices)}.")
        return value[:500]


@dataclass
class AuthSettings:
    # --- Almacenamiento ---
    # Cualquier URL de SQLAlchemy: sqlite:///ruta/auth.sqlite3, postgresql+psycopg://…, mysql+pymysql://…
    database_url: str = "sqlite:///auth.sqlite3"
    # Alternativa con el formato de DATABASES["default"] de Django (tiene prioridad sobre database_url):
    # {"ENGINE": "postgresql", "NAME": …, "USER": …, "PASSWORD": …, "HOST": …, "PORT": …}
    database: dict[str, Any] | None = None
    # Varias bases (DATABASES de Django): {"default": {...}, "replica": {...}, "ventas": "postgresql://…"}.
    # Cada alias acepta además CONN_MAX_AGE y READ_ONLY. Tiene prioridad sobre database y database_url.
    databases: dict[str, Any] | None = None
    # Routers (DATABASE_ROUTERS de Django): rutas "paquete.modulo.Clase", clases o instancias. Ver djauth.routers.
    database_routers: tuple[Any, ...] = ()
    # Segundos antes de renovar una conexión del pool (como CONN_MAX_AGE): evita conexiones viejas.
    database_conn_max_age: int = 1800
    table_prefix: str = "auth_"

    # --- Sitio (lo que ve el usuario) ---
    site_name: str = "Administración"
    brand_color: str = "#2a78d6"
    home_url: str = "/"  # a dónde se va tras iniciar sesión si no hay `next`

    # --- Tipo de autenticación (se pueden activar los dos a la vez) ---
    # Sesión: cookie HttpOnly, para navegadores (páginas, paneles). Es la de Django.
    enable_sessions: bool = True
    # Bearer: `Authorization: Bearer <token>`, para APIs, apps móviles e integraciones.
    # Los tokens son opacos y revocables (se guardan cifrados con hash, como las sesiones), no JWT:
    # cerrar sesión, cambiar la contraseña o desactivar al usuario los invalida al instante.
    enable_bearer: bool = True
    bearer_token_age: int = 60 * 60 * 12  # 12 horas

    # --- Sesiones (equivalentes a SESSION_COOKIE_* de Django) ---
    session_cookie_name: str = "sessionid"
    session_cookie_age: int = 60 * 60 * 24 * 14  # 2 semanas
    session_cookie_secure: bool = False  # True cuando el sitio se sirve por HTTPS
    session_cookie_samesite: str = "lax"  # "lax", "strict" o "none" (este último exige session_cookie_secure)

    # --- Protección CSRF y proxies ---
    # Orígenes externos que pueden enviar peticiones con la cookie de sesión (p. ej. un frontend en
    # otro dominio): ("https://app.empresa.com",). El propio sitio siempre está permitido.
    trusted_origins: tuple[str, ...] = ()
    # Leer la IP real de `X-Forwarded-For` (solo detrás de un proxy de confianza; si no, se falsifica).
    trust_proxy_headers: bool = False

    # --- Contraseñas ---
    password_iterations: int = 1_200_000  # PBKDF2-SHA256, el valor de Django 6.0
    password_min_length: int = 8
    password_max_length: int = 1024  # evita gastar CPU cifrando contraseñas gigantes
    password_reset_timeout: int = 60 * 60 * 24 * 3  # validez del enlace de restablecimiento
    # Clave para firmar los enlaces. Sin definir, se genera una y se guarda en la base de datos.
    secret_key: str | None = None

    # --- Protección del inicio de sesión ---
    login_max_failures: int = 5
    login_lockout_seconds: int = 300

    # --- Campo con el que se inicia sesión (USERNAME_FIELD de Django): uno u otro, no los dos ---
    # "username": nombre de usuario (por defecto). "email": el correo, que pasa a ser obligatorio y
    # único sin distinguir mayúsculas; el username interno se mantiene igual al correo.
    username_field: str = "username"

    # --- Backends de autenticación (AUTHENTICATION_BACKENDS de Django) ---
    # Rutas "paquete.modulo.Clase", clases o instancias. Se prueban en orden. Ver `djauth.backends`.
    authentication_backends: tuple[Any, ...] = ("djauth.backends.ModelBackend",)

    # --- Personalización del usuario ---
    # Campos extra guardados en JSON (sin tocar la tabla). Ver `ExtraField`.
    extra_fields: tuple[ExtraField, ...] = ()
    # Columnas propias del usuario, como heredar de AbstractUser en Django: una clase con columnas de
    # SQLAlchemy (`telefono: Mapped[str] = mapped_column(String(30), default="")`). Se añaden a la
    # tabla al arrancar y aparecen en la API y en la administración. Ver README, "Extender el usuario".
    user_mixin: type | None = None

    # --- Historial de cambios del usuario ---
    # Guarda cada alta, modificación (valor anterior y nuevo por campo), cambio de contraseña (sin
    # valores) y eliminación de usuarios, con quién lo hizo, desde qué IP y el motivo. Solo cambios
    # del usuario: los inicios de sesión y demás acciones van en el registro general. Ver docs.
    user_history: bool = True

    # --- Primer arranque ---
    # (usuario, contraseña, email): crea este superusuario si la base no tiene ningún usuario.
    bootstrap_superuser: tuple[str, str, str] | None = None

    # Permisos propios del proyecto: {"app_label": {"codename": "Descripción"}}
    permissions: dict[str, dict[str, str]] = field(default_factory=dict)
