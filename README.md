# fastapi-djauth

[![CI](https://github.com/carlosvisbal/fastapi-djauth/actions/workflows/ci.yml/badge.svg)](https://github.com/carlosvisbal/fastapi-djauth/actions/workflows/ci.yml)

Usuarios, grupos (roles), permisos y una **vista de administración** para FastAPI, con el mismo modelo que `django.contrib.auth`. Autenticación por **sesión (cookie)**, por **token Bearer**, o las dos a la vez.

- Usuario con `username`, `email`, nombre, `is_active`, `is_staff`, `is_superuser`, `last_login`, `date_joined` y **campos propios** sin migraciones.
- Grupos con permisos (roles) y permisos individuales. `user.has_perm("app.codename")` como en Django.
- Administración web lista: usuarios, grupos, permisos y registro de acciones.
- Páginas de inicio de sesión, "Mi cuenta" y restablecimiento de contraseña.
- Contraseñas en el formato de Django (`pbkdf2_sha256`, 1 200 000 iteraciones): se pueden importar usuarios de un proyecto Django.
- SQLite, PostgreSQL o MySQL (cualquier base de SQLAlchemy 2).
- Comandos `createsuperuser`, `changepassword` y `listusers`.

## Instalación

```bash
pip install "git+https://github.com/carlosvisbal/fastapi-djauth.git"   # desde GitHub
pip install fastapi-djauth                # desde PyPI, cuando esté publicado
pip install "fastapi-djauth[postgres]"    # con el controlador de PostgreSQL
```

En `requirements.txt`: `fastapi-djauth @ git+https://github.com/carlosvisbal/fastapi-djauth.git@v1.0.0`

## Uso en 10 líneas

```python
from fastapi import Depends, FastAPI
from djauth import AuthKit, AuthSettings, AuthUser, current_user, require_perm

kit = AuthKit(
    AuthSettings(
        database_url="sqlite:///./auth.sqlite3",
        bootstrap_superuser=("admin", "Cambiar-Esta-Clave-1", "admin@example.com"),
        permissions={"ventas": {"aprobar_pedido": "Puede aprobar pedidos"}},
    )
).init()

app = FastAPI()


@app.post("/pedidos/{id}/aprobar")
def aprobar(id: int, user: AuthUser = Depends(require_perm("ventas.aprobar_pedido"))):
    return {"aprobado_por": user.username}


kit.install(app)  # rutas /auth/api/* y páginas /auth/login, /auth/admin, /auth/account
```

Abra `/auth/admin`, entre con el superusuario y cree grupos y usuarios. Hay un ejemplo completo en [examples/app.py](examples/app.py).

## Dependencias (equivalentes de Django)

| djauth | Django |
|---|---|
| `Depends(current_user)` | `@login_required` |
| `Depends(require_perm("app.codename", ...))` | `@permission_required` |
| `Depends(require_staff)` | `@staff_member_required` |
| `Depends(require_superuser)` | `user.is_superuser` |
| `Depends(optional_user)` | `request.user` (puede ser anónimo: `None`) |
| `ws_user(websocket)` | usuario de un WebSocket |
| `user.has_perm()`, `has_perms()`, `has_module_perms()`, `get_full_name()` | igual |

## Proteger toda la aplicación

```python
from djauth import rule

kit.install(
    app,
    protect=True,  # todo exige sesión o token, salvo lo exento
    exempt={"/health"},  # rutas públicas
    exempt_prefixes=("/public/",),
    rules=[  # permisos por ruta, sin tocar cada función
        rule(r"^/pedidos", "ventas.view_pedido", methods=["GET"]),
        rule(r"^/pedidos", "ventas.change_pedido"),
    ],
    api_key="…",  # opcional: credencial de máquina con acceso total
)
```

Sin credenciales, un navegador se redirige a `/auth/login?next=…` y una API recibe `401`. Con credenciales pero sin el permiso, `403`. Cubre también los WebSocket.

## Sesión o Bearer

| | Sesión (cookie) | Bearer |
|---|---|---|
| Para | Navegadores, paneles | APIs, apps móviles, integraciones, scripts |
| Cómo se obtiene | `POST /auth/api/login` | `POST /auth/api/token` (JSON o formulario OAuth2) |
| Se envía en | Cookie `HttpOnly`, `SameSite=Lax` | `Authorization: Bearer <token>` (WebSocket: `?access_token=`) |
| Activar o desactivar | `enable_sessions` | `enable_bearer` |
| Duración | `session_cookie_age` (2 semanas) | `bearer_token_age` (12 h) |

Se pueden usar las dos a la vez. El botón **Authorize** de `/docs` funciona con el token. Si desactiva las sesiones, las páginas de administración guardan el token en la pestaña (`sessionStorage`) y lo envían como Bearer.

Los tokens son **opacos y revocables**, no JWT: en la base solo se guarda su hash SHA-256, y cerrar sesión, cambiar la contraseña, desactivar al usuario o "Cerrar sus sesiones" desde la administración los invalida al instante.

## Seguridad

- **Contraseñas:** PBKDF2-SHA256 con 1 200 000 iteraciones y sal aleatoria; se recifran solas al entrar si se subió el número de iteraciones. Validadores de Django: longitud mínima, contraseñas comunes, solo números y parecido a los datos del usuario.
- **Fuerza bruta:** bloqueo temporal por usuario e IP tras `login_max_failures` intentos (`429` con `Retry-After`). Un usuario inexistente responde igual y tarda lo mismo que una contraseña errónea.
- **CSRF:** las peticiones que modifican datos con cookie de sesión deben venir del mismo origen (`Origin` / `Sec-Fetch-Site`). Los clientes Bearer no lo necesitan. Orígenes externos de confianza: `trusted_origins`.
- **Fijación de sesión:** cada inicio de sesión crea una sesión nueva y descarta la anterior.
- **Escalada de privilegios:** un administrador que no es superusuario no puede crear ni modificar superusuarios, ni conceder permisos que él mismo no tiene. Siempre queda al menos un superusuario activo; nadie puede desactivarse ni eliminarse a sí mismo.
- **Restablecimiento:** enlaces firmados de un solo uso, que caducan (`password_reset_timeout`) y dejan de valer al cambiar la contraseña o al iniciar sesión. El token va en el fragmento de la URL (`#`), así que no llega a los logs del servidor.
- **Páginas:** `Content-Security-Policy` estricta (sin scripts en línea ni recursos externos), `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`.
- **Registro de acciones:** quién creó, modificó o eliminó qué, inicios de sesión, cambios de contraseña y cierres de sesión.

En producción: sirva el sitio por **HTTPS** y ponga `session_cookie_secure=True`. Si hay un proxy delante, `trust_proxy_headers=True` para registrar la IP real (solo si el proxy es de confianza).

## Personalizar el usuario

```python
from djauth import ExtraField

AuthSettings(
    extra_fields=(
        ExtraField("sede", "Sede", "choice", ("Norte", "Sur"), required=True),
        ExtraField("turno", "Turno", "number", help_text="1, 2 o 3"),
        ExtraField("supervisor", "Es supervisor", "bool"),
    )
)
```

Se guardan en `user.extra` (columna JSON, sin migraciones) y aparecen en el formulario de administración. Tipos: `text`, `number`, `bool`, `choice`.

## Permisos y roles del proyecto

```python
kit.register_permissions("inventario", {"ajustar_stock": "Puede ajustar el stock"})
kit.ensure_group("Bodeguero", ["inventario.ajustar_stock"])  # solo lo crea si no existe
```

`ensure_group` no pisa los cambios hechos luego desde la administración. Los permisos de la administración (`auth.view_user`, `auth.add_user`, `auth.change_user`, `auth.delete_user`, `auth.*_group`, `auth.view_logentry`) siguen los nombres de Django.

## Uso sin FastAPI

El núcleo (`AuthKit`) no depende de FastAPI: `kit.create_user(...)`, `kit.authenticate(...)`, `kit.update_user(...)`, `kit.list_users(...)`, `kit.set_password(...)`, `kit.make_reset_token(...)`, etc. Sirve para scripts, tareas o importaciones.

## Comandos

```bash
djauth --db sqlite:///auth.sqlite3 createsuperuser --username admin --email admin@example.com
djauth --db sqlite:///auth.sqlite3 changepassword admin
djauth --db sqlite:///auth.sqlite3 listusers
```

La contraseña se pide por teclado; en scripts, use la variable `DJAUTH_PASSWORD`.

## API

Todas bajo `/auth/api` (cambie el prefijo con `install(app, prefix="/cuentas")`):

| Método | Ruta | Para |
|---|---|---|
| POST | `/login`, `/logout`, `/token` | Sesión, cierre y token Bearer |
| GET, PATCH | `/me` | Mis datos, grupos y permisos |
| POST | `/me/password` | Cambiar mi contraseña |
| POST | `/reset/confirm` | Fijar contraseña con un enlace |
| GET, POST | `/users` | Listar (búsqueda, filtros, orden, paginado) y crear |
| GET, PATCH, DELETE | `/users/{id}` | Ver, modificar y eliminar |
| POST | `/users/{id}/password`, `/reset-link`, `/logout` | Asignar contraseña, enlace de restablecimiento, cerrar sesiones |
| GET, POST | `/groups` · GET, PATCH, DELETE `/groups/{id}` | Grupos (roles) |
| GET | `/permissions`, `/log` | Permisos disponibles y registro de acciones |

Los errores de validación responden `400` con `{"detail": "...", "errors": {"campo": ["mensaje"]}}`.

## Pruebas

```bash
pip install -e ".[test]"
pytest
```

## Diferencias con Django

- No hay migraciones: `init()` crea las tablas que faltan. Los campos propios van en `extra` (JSON).
- No envía correos: la administración genera el enlace de restablecimiento y usted lo hace llegar.
- No hay permisos por objeto ni "backends" intercambiables.
