# 2. Configuración

Todo se configura con `AuthSettings(...)`. Solo `database_url` suele ser obligatorio cambiarlo.

```python
from djauth import AuthKit, AuthSettings

kit = AuthKit(AuthSettings(
    database_url="postgresql+psycopg://usuario:clave@localhost/miapp",
    site_name="Mi empresa",
    session_cookie_secure=True,
)).init()
```

## Base de datos

Dos formas equivalentes:

```python
AuthSettings(database={
    "ENGINE": "postgresql",                        # o mysql, sqlite, oracle, mssql
    "NAME": "miapp",
    "USER": "app",
    "PASSWORD": os.environ["DB_PASSWORD"],          # caracteres como @ / # no necesitan escaparse
    "HOST": "localhost",
    "PORT": "5432",
    "OPTIONS": {"sslmode": "require"},             # parámetros del controlador
})
# o con una URL de SQLAlchemy:
AuthSettings(database_url="postgresql+psycopg://app:clave@localhost:5432/miapp")
```

| Opción | Por defecto | Qué es |
|---|---|---|
| `database` | `None` | Diccionario con `ENGINE`, `NAME`, `USER`, `PASSWORD`, `HOST`, `PORT` y `OPTIONS`. Tiene prioridad sobre `database_url`. |
| `database_url` | `sqlite:///auth.sqlite3` | URL de SQLAlchemy. |
| `database_conn_max_age` | 1800 | Segundos antes de renovar una conexión del pool. |
| `table_prefix` | `auth_` | Prefijo de las tablas (`auth_user`, `auth_group`…). |

**Motores** (`ENGINE`): `postgresql` (también PostGIS), `mysql` (también MariaDB), `sqlite`, `oracle` y `mssql`. También acepta los nombres de Django (`django.db.backends.postgresql`…), para copiar una configuración existente.

**Controlador:** se elige el que esté instalado (PostgreSQL: `psycopg`, luego `psycopg2`; MySQL: `PyMySQL`, luego `mysqlclient`). Fuerce uno con `"DRIVER": "psycopg2"`. Instalar: `pip install "fastapi-djauth[postgres]"` o `"fastapi-djauth[mysql]"`.

Las conexiones se verifican antes de usarse (una conexión cortada por el servidor no produce errores).

## Sitio

| Opción | Por defecto | Qué es |
|---|---|---|
| `site_name` | `Administración` | Nombre en las páginas de acceso y administración. |
| `brand_color` | `#2a78d6` | Color principal de esas páginas. |
| `home_url` | `/` | A dónde se va tras iniciar sesión (si no hay `?next=`). |

## Tipo de autenticación ([guía](04-sesion-y-bearer.md))

| Opción | Por defecto | Qué es |
|---|---|---|
| `enable_sessions` | `True` | Inicio de sesión con cookie (navegadores). |
| `enable_bearer` | `True` | Tokens `Authorization: Bearer` (APIs, móviles, scripts). |
| `bearer_token_age` | 12 h | Duración de un token, en segundos. |
| `session_cookie_name` | `sessionid` | Nombre de la cookie. |
| `session_cookie_age` | 2 semanas | Duración de la sesión, en segundos. |
| `session_cookie_secure` | `False` | Póngalo en `True` con HTTPS. |
| `session_cookie_samesite` | `lax` | Política SameSite de la cookie. |

## Seguridad ([guía](10-seguridad.md))

| Opción | Por defecto | Qué es |
|---|---|---|
| `trusted_origins` | `()` | Otros dominios suyos que pueden usar la cookie (frontend separado). |
| `trust_proxy_headers` | `False` | Leer la IP real de `X-Forwarded-For` (solo detrás de su propio proxy). |
| `password_iterations` | 1 200 000 | Iteraciones de PBKDF2 (valor recomendado actual). |
| `password_min_length` | 8 | Longitud mínima de la contraseña. |
| `password_max_length` | 1024 | Longitud máxima (evita abusos de CPU). |
| `password_reset_timeout` | 3 días | Validez del enlace para restablecer contraseña, en segundos. |
| `secret_key` | generada | Clave para firmar enlaces. Si no la define, se genera y se guarda en la base. |
| `login_max_failures` | 5 | Intentos fallidos antes del bloqueo temporal. |
| `login_lockout_seconds` | 300 | Duración del bloqueo. |

## Usuarios y permisos

| Opción | Por defecto | Qué es |
|---|---|---|
| `username_field` | `username` | Con qué se inicia sesión: `username` o `email` (uno u otro, como `USERNAME_FIELD`). [Guía](05-usuarios-grupos-permisos.md#iniciar-sesión-con-usuario-o-con-correo). |
| `authentication_backends` | `("djauth.backends.ModelBackend",)` | Backends que se prueban en orden. [Guía](06-backends.md). |
| `user_mixin` | `None` | Clase con columnas propias del usuario. [Guía](07-extender-usuario.md). |
| `extra_fields` | `()` | Campos propios guardados en JSON. [Guía](07-extender-usuario.md). |
| `permissions` | `{}` | Permisos del proyecto: `{"ventas": {"aprobar": "Puede aprobar"}}`. |
| `bootstrap_superuser` | `None` | `(usuario, contraseña, email)`: se crea si la base no tiene usuarios. |
| `user_history` | `True` | Guarda el historial de cambios de cada usuario (valor anterior y nuevo). [Guía](14-historial-de-cambios.md). |

## Leer la configuración del entorno

`AuthSettings` es una clase normal: pásele lo que lea de su configuración.

```python
import os
AuthSettings(
    database_url=os.environ["DATABASE_URL"],
    session_cookie_secure=os.environ.get("HTTPS") == "1",
    bootstrap_superuser=("admin", os.environ["ADMIN_PASSWORD"], "") if os.environ.get("ADMIN_PASSWORD") else None,
)
```
