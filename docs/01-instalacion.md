# 1. Instalación y primer uso

## Instalar

```bash
pip install "git+https://github.com/carlosvisbal/fastapi-djauth.git"
```

Requiere Python 3.11 o superior. Instala FastAPI, SQLAlchemy 2 y pydantic 2 si no los tiene.

## Primer uso

```python
# main.py
from fastapi import Depends, FastAPI
from djauth import AuthKit, AuthSettings, AuthUser, current_user

kit = AuthKit(AuthSettings(
    database_url="sqlite:///./auth.sqlite3",
    bootstrap_superuser=("admin", "Cambiar-Esta-Clave-1", "admin@example.com"),
)).init()

app = FastAPI()

@app.get("/")
def inicio(user: AuthUser = Depends(current_user)):
    return {"hola": user.username}

kit.install(app)
```

```bash
uvicorn main:app --reload
```

1. Abra `http://localhost:8000/auth/login` y entre con `admin` / `Cambiar-Esta-Clave-1`.
2. Cambie la contraseña en `http://localhost:8000/auth/account`.
3. Cree grupos y usuarios en `http://localhost:8000/auth/admin`.

## Qué hace cada línea

| Línea | Qué hace |
|---|---|
| `AuthKit(AuthSettings(...))` | Configura el módulo. Ver [Configuración](02-configuracion.md). |
| `.init()` | Crea las tablas que falten, los permisos declarados y el superusuario inicial (solo si no hay usuarios). |
| `Depends(current_user)` | La ruta exige iniciar sesión. Ver [Proteger rutas](03-proteger-rutas.md). |
| `kit.install(app)` | Añade la API (`/auth/api/...`) y las páginas (`/auth/login`, `/auth/admin`, `/auth/account`, `/auth/reset`). |

> El superusuario inicial se crea una sola vez. Después, quite la contraseña del código (léala de una variable de entorno) o use `djauth createsuperuser` ([Comandos](11-comandos.md)).

Siguiente: [Proteger rutas](03-proteger-rutas.md).
