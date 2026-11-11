# fastapi-djauth

[![PyPI](https://img.shields.io/pypi/v/fastapi-djauth)](https://pypi.org/project/fastapi-djauth/)
[![Python](https://img.shields.io/pypi/pyversions/fastapi-djauth)](https://pypi.org/project/fastapi-djauth/)
[![CI](https://github.com/carlosvisbal/fastapi-djauth/actions/workflows/ci.yml/badge.svg)](https://github.com/carlosvisbal/fastapi-djauth/actions/workflows/ci.yml)
[![Tipado](https://img.shields.io/badge/tipado-mypy-blue)](https://github.com/carlosvisbal/fastapi-djauth/blob/main/pyproject.toml)
[![Licencia: MIT](https://img.shields.io/badge/licencia-MIT-green)](https://github.com/carlosvisbal/fastapi-djauth/blob/main/LICENSE)

**Usuarios, roles, permisos y administración para FastAPI.** Sesión por cookie o token Bearer, una vista de administración lista, y la seguridad resuelta.

```python
from fastapi import Depends, FastAPI
from djauth import AuthKit, AuthSettings, AuthUser, require_perm

kit = AuthKit(AuthSettings(
    database={"ENGINE": "postgresql", "NAME": "miapp", "USER": "app", "PASSWORD": "…", "HOST": "localhost"},
    permissions={"ventas": {"aprobar_pedido": "Puede aprobar pedidos"}},
)).init()

app = FastAPI()

@app.post("/pedidos/{id}/aprobar")
def aprobar(id: int, user: AuthUser = Depends(require_perm("ventas.aprobar_pedido"))):
    return {"aprobado_por": user.username}

kit.install(app)   # API en /auth/api y páginas: /auth/login, /auth/admin, /auth/account
```

## Qué trae

- **Usuarios, grupos (roles) y permisos** `app.codename`, con `user.has_perm()`, decoradores (`@login_required`, `@permission_required`) o dependencias.
- **Configurable sin código extra:** conexión a la base por diccionario, inicio de sesión con usuario o con correo, backends de autenticación propios (LDAP, otros sistemas) y columnas propias en el usuario.
- **Sesión o Bearer:** cookie `HttpOnly` para navegadores, tokens opacos y revocables para APIs; uno, otro o los dos.
- **Administración web:** usuarios, grupos, permisos y registro de acciones; inicio de sesión, "Mi cuenta" y restablecimiento de contraseña.
- **Historial de cambios del usuario:** cada alta, modificación (valor anterior y nuevo por campo), cambio de contraseña y baja, con quién, cuándo, desde qué IP y por qué. Nunca guarda contraseñas.
- **Seguro por defecto:** contraseñas PBKDF2-SHA256, bloqueo por fuerza bruta, CSRF, protección de WebSocket, sin escalada de privilegios entre administradores, cabeceras de seguridad.
- **Errores descriptivos:** cada error trae mensaje, código fijo, campo afectado y cómo resolverlo.
- **Cualquier base:** SQLite, PostgreSQL, MySQL/MariaDB, Oracle o SQL Server (SQLAlchemy 2), probadas contra servidores reales en cada cambio.
- **Plantilla de proyecto:** `djauth startproject` crea una aplicación nueva lista para producción.

## Proyecto nuevo en un minuto

```bash
pip install fastapi-djauth
djauth startproject inventario --db postgresql
```

Crea una aplicación FastAPI completa con arquitectura por capas, usuarios y permisos, Alembic, Docker, pruebas y CI. Usted elige las versiones probadas o las últimas de cada librería. Ver [Proyecto nuevo](https://github.com/carlosvisbal/fastapi-djauth/blob/main/docs/16-nuevo-proyecto.md).

## Instalación

```bash
pip install fastapi-djauth                      # PyPI
pip install "fastapi-djauth[postgres]"          # con el controlador de PostgreSQL
pip install "git+https://github.com/carlosvisbal/fastapi-djauth.git"   # última versión de GitHub
```

Requiere Python 3.11+.

## Documentación

| | |
|---|---|
| **Empezar** | [Proyecto nuevo](https://github.com/carlosvisbal/fastapi-djauth/blob/main/docs/16-nuevo-proyecto.md) · [Instalación y primer uso](https://github.com/carlosvisbal/fastapi-djauth/blob/main/docs/01-instalacion.md) · [Configuración](https://github.com/carlosvisbal/fastapi-djauth/blob/main/docs/02-configuracion.md) · [Bases de datos](https://github.com/carlosvisbal/fastapi-djauth/blob/main/docs/15-bases-de-datos.md) · [Desde Django](https://github.com/carlosvisbal/fastapi-djauth/blob/main/docs/13-desde-django.md) |
| **Usar** | [Proteger rutas](https://github.com/carlosvisbal/fastapi-djauth/blob/main/docs/03-proteger-rutas.md) · [Sesión o Bearer](https://github.com/carlosvisbal/fastapi-djauth/blob/main/docs/04-sesion-y-bearer.md) · [Usuarios, grupos y permisos](https://github.com/carlosvisbal/fastapi-djauth/blob/main/docs/05-usuarios-grupos-permisos.md) |
| **Personalizar** | [Backends de autenticación](https://github.com/carlosvisbal/fastapi-djauth/blob/main/docs/06-backends.md) · [Extender el usuario](https://github.com/carlosvisbal/fastapi-djauth/blob/main/docs/07-extender-usuario.md) |
| **Operar** | [Administración web](https://github.com/carlosvisbal/fastapi-djauth/blob/main/docs/08-administracion.md) · [Historial de cambios](https://github.com/carlosvisbal/fastapi-djauth/blob/main/docs/14-historial-de-cambios.md) · [Comandos](https://github.com/carlosvisbal/fastapi-djauth/blob/main/docs/11-comandos.md) · [Seguridad](https://github.com/carlosvisbal/fastapi-djauth/blob/main/docs/10-seguridad.md) |
| **Referencia** | [API REST](https://github.com/carlosvisbal/fastapi-djauth/blob/main/docs/12-api.md) · [Errores](https://github.com/carlosvisbal/fastapi-djauth/blob/main/docs/09-errores.md) · [Cambios](https://github.com/carlosvisbal/fastapi-djauth/blob/main/CHANGELOG.md) |

¿Viene de Django? Los conceptos y la configuración le resultarán familiares, y puede importar sus usuarios con su contraseña: vea [Desde Django](https://github.com/carlosvisbal/fastapi-djauth/blob/main/docs/13-desde-django.md). El paquete **no** necesita Django instalado.

Hay un ejemplo completo en [examples/app.py](https://github.com/carlosvisbal/fastapi-djauth/blob/main/examples/app.py).

## Seguridad

Lea [docs/10-seguridad.md](https://github.com/carlosvisbal/fastapi-djauth/blob/main/docs/10-seguridad.md) antes de poner el servicio en producción. Para informar una vulnerabilidad, use el aviso privado de GitHub ([SECURITY.md](https://github.com/carlosvisbal/fastapi-djauth/blob/main/SECURITY.md)), no un issue público.

## Contribuir

Las contribuciones son bienvenidas. Vea [CONTRIBUTING.md](https://github.com/carlosvisbal/fastapi-djauth/blob/main/CONTRIBUTING.md): cómo preparar el entorno, las pruebas (también contra PostgreSQL y MySQL reales) y el proceso de publicación.

## Licencia

[MIT](https://github.com/carlosvisbal/fastapi-djauth/blob/main/LICENSE) © Carlos Daniel Visbal Atencia
