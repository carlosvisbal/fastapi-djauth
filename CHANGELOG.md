# Cambios

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el proyecto usa [versionado semántico](https://semver.org/lang/es/).

## [1.3.1] - 2026-11-11

Primera versión publicada en PyPI.

### Corregido
- **MySQL, Oracle y SQL Server:** agregar columnas propias (`user_mixin`) a una tabla existente fallaba porque los nombres iban entre comillas dobles y se usaba `ADD COLUMN` en todos los motores. Ahora se usan las comillas y la sintaxis de cada motor.
- Un controlador asíncrono (`asyncpg`, `aiomysql`…) se rechaza al arrancar con un error claro, en lugar de fallar después. Ya no se elige `asyncpg` automáticamente.
- **Oracle** no funcionaba: las claves primarias no se generaban (ahora usan `IDENTITY`) y los textos vacíos fallaban, porque Oracle guarda `''` como NULL. Ahora esos textos admiten NULL solo en Oracle y se leen como `''`, igual que hace Django.
- Las claves primarias usan `IDENTITY` en PostgreSQL, Oracle y SQL Server para las tablas nuevas. Las tablas existentes no cambian.

### Cambiado
- Versión mínima de SQLAlchemy: 2.0.24, la primera que escapa `#` en las contraseñas al mostrar la URL de conexión.
- El paquete declara sus tipos (`py.typed`) y pasa `mypy`.
- Nuevos extras `mssql` (`pymssql`, sin dependencias del sistema) y `oracle` en las pistas de instalación.

### Añadido
- Guía de [bases de datos](docs/15-bases-de-datos.md): conexión y particularidades de cada motor.
- CI con Python 3.11 a 3.14 en Linux, Windows y macOS, versiones mínimas de las dependencias, PostgreSQL, MySQL, Oracle y SQL Server reales, `mypy`, `bandit` y `pip-audit`.
- `djauth startproject`: crea un proyecto FastAPI nuevo con arquitectura por capas, djauth integrado, Alembic, Docker, pruebas y CI; con las versiones probadas o las últimas. Ver [Nuevo proyecto](docs/16-nuevo-proyecto.md).
- Publicación automática en TestPyPI y PyPI con *Trusted Publishing* y atestaciones firmadas.
- `CONTRIBUTING.md`, plantillas de issues y de pull requests, Dependabot y `llms.txt`.

## [1.3.0] - 2026-11-11

### Añadido
- **Historial de cambios del usuario** (tabla `auth_user_history`): cada alta, modificación (valor anterior y nuevo por campo), cambio de contraseña (sin valores) y eliminación, con quién lo hizo, cuándo, desde qué IP y el motivo. Se guarda en la misma transacción que el cambio y se conserva al eliminar el usuario. Solo cambios del usuario: inicios de sesión y demás acciones siguen en el registro general.
- Rutas `GET /auth/api/user-history` y `GET /auth/api/users/{id}/history`, método `kit.user_history()` y permiso `auth.view_userchange`.
- Motivo del cambio: `?reason=` en la API, `reason=` en `create_user`, `update_user`, `delete_user` y `set_password`, y un campo en el formulario de la administración.
- Pestaña *Cambios de usuarios* en la administración.
- Campos sensibles: `info={"sensitive": True}` en columnas propias y `ExtraField(..., sensitive=True)` registran que cambiaron, sin los valores.
- Opción `user_history` para desactivarlo.

### Cambiado
- Los mensajes de error de la conexión a la base sugieren los nombres cortos de motor (`postgresql`, `mysql`…).

## [1.2.0] - 2026-11-10

### Añadido
- Decoradores `@login_required`, `@permission_required`, `@staff_member_required`, `@superuser_required` y `@user_passes_test`, además de las dependencias `current_user`, `require_perm`, etc.

### Cambiado
- Los ejemplos usan los nombres cortos de motor (`"ENGINE": "postgresql"`) y ya no dan a entender que hace falta Django. Los nombres de Django se siguen aceptando.

## [1.1.0] - 2026-11-10

### Añadido
- **Backends de autenticación** (`authentication_backends`), el equivalente de `AUTHENTICATION_BACKENDS` de Django: `ModelBackend`, `AllowAllUsersModelBackend` y `BaseBackend` para escribir los suyos (LDAP, otros sistemas, otras credenciales). Permisos sumados de todos los backends.
- **Extender el usuario con columnas reales** (`user_mixin`), como `AbstractUser`: aparecen en la API y en la administración, se leen como `user.campo`, y las columnas nuevas se agregan solas a la tabla.
- **Errores descriptivos**: todas las respuestas llevan `detail`, `code`, `hint` y `errors` por campo; los errores de formato se traducen al español (`422`).
- **`DATABASES` de Django** (`database={"ENGINE": …, "NAME": …}`): conexión sin escribir la URL, con contraseñas escapadas y elección automática del controlador instalado. Conexiones verificadas antes de usarse.
- **`username_field`**, el equivalente de `USERNAME_FIELD`: iniciar sesión con el usuario o con el correo (único, sin distinguir mayúsculas, garantizado por la base).
- Documentación por temas en `docs/`.

### Seguridad
- Un WebSocket autenticado con cookie debe abrirse desde el mismo origen (evita el secuestro de WebSocket entre sitios, CSWSH).
- Un administrador que no es superusuario ya no puede modificar ni cambiar la contraseña de usuarios con permisos que él no tiene.
- El inicio de sesión rechaza peticiones con `Origin` de otro sitio aunque aún no haya cookie.
- La cookie de sesión se marca `Secure` automáticamente cuando la petición llega por HTTPS.

## [1.0.0] - 2026-11-10

### Añadido
- Usuarios, grupos (roles) y permisos con el modelo de `django.contrib.auth`.
- Autenticación por sesión (cookie) o token Bearer opaco y revocable.
- Administración web, inicio de sesión, "Mi cuenta" y restablecimiento de contraseña.
- Contraseñas PBKDF2-SHA256 compatibles con Django.
- Comandos `createsuperuser`, `changepassword` y `listusers`.
