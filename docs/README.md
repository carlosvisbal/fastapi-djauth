# Documentación de fastapi-djauth

Guías cortas, con el ejemplo primero. Si viene de Django, empiece por [Desde Django](13-desde-django.md).

| # | Guía | Para |
|---|---|---|
| 1 | [Instalación y primer uso](01-instalacion.md) | Tenerlo funcionando en 5 minutos |
| 2 | [Configuración](02-configuracion.md) | Todas las opciones de `AuthSettings` |
| 3 | [Proteger rutas](03-proteger-rutas.md) | `current_user`, `require_perm`, reglas por ruta, WebSocket |
| 4 | [Sesión o token Bearer](04-sesion-y-bearer.md) | Elegir cómo se autentica cada cliente |
| 5 | [Usuarios, grupos y permisos](05-usuarios-grupos-permisos.md) | Roles, permisos propios y uso desde código |
| 6 | [Backends de autenticación](06-backends.md) | `AUTHENTICATION_BACKENDS`: LDAP, otros sistemas |
| 7 | [Extender el usuario](07-extender-usuario.md) | Columnas propias (como `AbstractUser`) o campos JSON |
| 8 | [Administración web](08-administracion.md) | Qué hace cada pantalla |
| 9 | [Errores](09-errores.md) | Formato de las respuestas y todos los códigos |
| 10 | [Seguridad](10-seguridad.md) | Qué protege y qué configurar en producción |
| 11 | [Comandos](11-comandos.md) | `createsuperuser`, `changepassword`, `listusers` |
| 12 | [API REST](12-api.md) | Todas las rutas |
| 13 | [Desde Django](13-desde-django.md) | Equivalencias e importar usuarios con su contraseña |
| 14 | [Historial de cambios del usuario](14-historial-de-cambios.md) | Quién cambió qué dato, de qué valor a cuál, cuándo y por qué |
