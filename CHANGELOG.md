# Cambios

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el proyecto usa [versionado semántico](https://semver.org/lang/es/).

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
