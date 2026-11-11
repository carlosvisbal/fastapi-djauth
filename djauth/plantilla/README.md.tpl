# __nombre__

Proyecto FastAPI con usuarios, roles y permisos ([fastapi-djauth](https://github.com/carlosvisbal/fastapi-djauth)), creado con `djauth startproject`.

## Empezar

Requiere [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                   # instala todo (crea .venv)
uv run alembic upgrade head               # crea las tablas de la aplicación
uv run uvicorn __paquete__.main:create_app --factory --reload
```

- Documentación de la API: http://127.0.0.1:8000/docs. Inicie sesión antes en http://127.0.0.1:8000/auth/login.
- Administración de usuarios, roles y permisos: http://127.0.0.1:8000/auth/admin.
- El superusuario y su contraseña están en `.env` (`APP_ADMIN_USERNAME`, `APP_ADMIN_PASSWORD`).

Con Docker (incluye la base de datos):

```bash
docker compose up --build
```

## Estructura

```text
src/__paquete__/
├── main.py              create_app(): arma la aplicación (rutas, base de datos, usuarios)
├── core/
│   ├── config.py        configuración desde variables de entorno (APP_*) o .env
│   └── security.py      permisos y roles de la aplicación (fastapi-djauth)
├── db.py                SQLAlchemy: Base de los modelos y sesión por petición
├── models/              tablas (SQLAlchemy)
├── schemas/             datos de entrada y salida de la API (Pydantic)
├── services/            lógica del negocio, sin FastAPI
└── api/
    ├── router.py        registra los módulos de la API (/api/v1)
    ├── deps.py          dependencias comunes (sesión de base de datos, usuario actual)
    └── v1/productos.py  módulo de ejemplo completo
migrations/              migraciones de Alembic (tablas de la aplicación)
tests/                   pruebas (pytest)
```

Cada capa tiene una responsabilidad:

- **Rutas:** validan la entrada, piden el permiso y delegan.
- **Servicios:** contienen la lógica.
- **Modelos y esquemas:** separan la base de datos de lo que expone la API.

## Agregar un módulo

1. Modelo en `models/` (e impórtelo en `models/__init__.py`), esquemas en `schemas/`, lógica en `services/` y rutas en `api/v1/`.
2. Registre el router en `api/router.py`.
3. Declare sus permisos en `core/security.py` (`PERMISSIONS`) y agréguelos a los roles.
4. Proteja cada ruta con `Depends(require_perm("app.codename"))`.
5. Migración: `uv run alembic revision --autogenerate -m "agregar X"` y `uv run alembic upgrade head`.

## Seguridad

- **Toda ruta exige sesión o token**, salvo `/health`. Lo hace `install(app, protect=True)` en `main.py`, así que una ruta nueva nunca queda pública por olvido.
- `.env` tiene secretos generados al crear el proyecto: no lo suba al repositorio (ya está en `.gitignore`).
- **En producción** (`APP_ENVIRONMENT=produccion`):
  - la documentación interactiva se desactiva;
  - sirva por HTTPS con `APP_COOKIE_SECURE=true`;
  - detrás de un proxy, use `APP_TRUST_PROXY_HEADERS=true`.
- Guía de seguridad de djauth: https://github.com/carlosvisbal/fastapi-djauth/blob/main/docs/10-seguridad.md

## Comprobaciones

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

## Actualizar dependencias

`uv.lock` fija las versiones exactas, así que todos instalan lo mismo. Para pasar a las últimas versiones compatibles y comprobar que todo sigue bien:

```bash
uv lock --upgrade && uv sync && uv run pytest
```
