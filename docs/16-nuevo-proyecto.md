# 16. Crear un proyecto nuevo (`djauth startproject`)

Para proyectos **nuevos**, un comando crea una aplicación FastAPI completa, lista para desarrollar, con djauth integrado. Es el equivalente a `django-admin startproject`.

```bash
pip install fastapi-djauth            # o: uvx --from fastapi-djauth djauth startproject …
djauth startproject inventario
```

```text
Proyecto creado en inventario

  Superusuario: admin  ·  contraseña: dqqcRFFGKrYdMRMkXQs
  (está en .env; cámbiela tras el primer inicio de sesión)

Siguientes pasos:
  cd inventario
  uv sync
  uv run alembic upgrade head
  uv run uvicorn inventario.main:create_app --factory --reload
```

Requiere [uv](https://docs.astral.sh/uv/) para instalar y ejecutar el proyecto generado.

## Opciones

| Opción | Valores | Por defecto | Para |
|---|---|---|---|
| `nombre` | minúsculas, números y `_` | (obligatorio) | Nombre del paquete de Python (`inventario`, `control_calidad`) |
| `carpeta` | ruta | `./<nombre>` | Dónde crearlo. Debe no existir o estar vacía. |
| `--db` | `sqlite`, `postgresql`, `mysql` | `sqlite` | Base de datos: instala el controlador y prepara `compose.yaml` con el servidor |
| `--versiones` | `probadas`, `ultimas` | `probadas` | Ver abajo |
| `--titulo` | texto | el nombre | Nombre visible de la aplicación |
| `--sin-lock` | | | No ejecutar `uv lock` al terminar (sin conexión, por ejemplo) |

```bash
djauth startproject inventario --db postgresql --titulo "Inventario general"
djauth startproject laboratorio --versiones ultimas
```

## Versiones: probadas o últimas

- **`probadas`** (por defecto): fija las versiones exactas de FastAPI, SQLAlchemy, Pydantic, Alembic, pytest, Ruff y mypy con las que se probó la plantilla en esta versión de djauth. Es lo más seguro: el proyecto funciona igual hoy que dentro de un año.
- **`ultimas`**: solo pide un mínimo compatible, y `uv` instala la versión más reciente de cada una al crear el proyecto. Úsela si quiere estrenar todo lo nuevo.

En los dos casos, `uv.lock` deja fijas las versiones instaladas: todo el equipo y el servidor instalan exactamente lo mismo. Para actualizar más adelante:

```bash
uv lock --upgrade && uv sync && uv run pytest
```

## Qué trae

```text
inventario/
├── src/inventario/
│   ├── main.py              create_app(): arma la aplicación
│   ├── core/config.py       configuración por variables de entorno (APP_*) o .env
│   ├── core/security.py     permisos y roles de la aplicación (djauth)
│   ├── db.py                SQLAlchemy 2: Base y una sesión por petición
│   ├── models/              tablas
│   ├── schemas/             entrada y salida de la API (Pydantic)
│   ├── services/            lógica del negocio, sin FastAPI
│   └── api/v1/productos.py  módulo de ejemplo completo (CRUD con permisos)
├── migrations/              Alembic, con la primera migración
├── tests/                   pytest: salud, acceso, CRUD y permisos por rol
├── Dockerfile               imagen de producción (usuario sin privilegios, sonda de salud)
├── compose.yaml             aplicación + base de datos
├── .github/workflows/ci.yml Ruff, mypy y pytest en cada cambio
├── .env                     secretos generados para este proyecto (no se sube)
└── .env.example             plantilla de configuración (sí se sube)
```

La arquitectura separa responsabilidades:

- **Rutas** (`api/`): validan la entrada, piden el permiso y delegan.
- **Servicios** (`services/`): la lógica, sin FastAPI, así que se prueba y se reutiliza (tareas, scripts) sin levantar el servidor.
- **Esquemas** (`schemas/`): lo que entra y sale de la API, separado de los **modelos** (`models/`) de la base de datos, para no exponer columnas internas por accidente.
- **Configuración** (`core/config.py`): con `pydantic-settings`, validada al arrancar.
- **Fábrica** `create_app(settings)`: las pruebas crean la aplicación con su propia configuración y base de datos.

El README del proyecto explica cómo agregar un módulo nuevo paso a paso.

## Seguridad del proyecto generado

- **Toda ruta exige sesión o token por defecto** (`install(app, protect=True)`), salvo `/health`. Una ruta nueva nunca queda pública por olvido. Además, cada ruta pide su permiso con `require_perm`.
- `.env` se crea con una clave secreta, una contraseña del superusuario y una de la base de datos aleatorias y propias de ese proyecto. Solo su dueño puede leer el archivo (permisos `600`), y `.gitignore` impide subirlo.
- La imagen de Docker corre con un usuario sin privilegios, sin herramientas de compilación, y con las dependencias fijadas por `uv.lock`.
- En producción (`APP_ENVIRONMENT=produccion`, el valor por defecto en Docker) se desactiva la documentación interactiva.
- Ruff incluye las reglas de seguridad de Bandit (`S`) y mypy corre en modo estricto.
- El comando nunca sobrescribe: si la carpeta existe y tiene archivos, se detiene sin tocar nada.

## Con Docker

```bash
docker compose up --build
```

Levanta la aplicación y la base de datos que eligió, aplica las migraciones y deja la API en http://127.0.0.1:8000. Para usar otro puerto: `APP_PORT=8080 docker compose up`.
