# 8. Administración web

`kit.install(app)` añade estas páginas (cambie `/auth` con `install(app, prefix="/cuentas")`):

| Página | Quién | Qué hace |
|---|---|---|
| `/auth/login` | Todos | Inicio de sesión. Vuelve a `?next=` (solo rutas del mismo sitio). |
| `/auth/account` | Usuarios con sesión | Datos personales, grupos y permisos propios, cambio de contraseña. |
| `/auth/admin` | Personal (`is_staff`) | Administración (abajo). |
| `/auth/reset#uid=…&token=…` | Quien tiene el enlace | Elegir contraseña nueva. |

## Pestañas de `/auth/admin`

Cada pestaña y botón aparece solo si el usuario tiene el permiso correspondiente.

| Pestaña | Permite |
|---|---|
| **Usuarios** | Buscar, filtrar (estado, acceso, grupo), ordenar y paginar. Crear y editar: datos, campos propios, activo, acceso a la administración, superusuario (solo un superusuario lo concede), grupos y permisos individuales (con buscador y los heredados de sus grupos). Acciones: enlace para nueva contraseña, asignar contraseña, cerrar sus sesiones, ver su historial, eliminar. |
| **Grupos y roles** | Crear, renombrar, elegir permisos (marcar todos o ninguno), ver cuántos miembros tiene, eliminar. |
| **Permisos** | Lista con buscador y origen de cada permiso: **Código** (lo declara la aplicación) o **Propio**. Crear permisos propios, cambiar su descripción y eliminarlos (`auth.add_permission`, `change_permission`, `delete_permission`). [Reglas](05-usuarios-grupos-permisos.md#crear-permisos-desde-la-administración). |
| **Cambios de usuarios** | Solo los cambios de los datos de cada usuario: valor anterior y nuevo por campo, quién, cuándo, IP y motivo. Se filtra por acción y campo. El formulario del usuario tiene un campo *Motivo del cambio* y el botón *Historial de cambios*. Requiere `auth.view_userchange`. [Guía](14-historial-de-cambios.md). |
| **Registro** | Quién hizo qué y cuándo: altas, cambios (con los campos modificados), bajas de usuarios, grupos y permisos, contraseñas, inicios de sesión y cierres de sesión. |

## Restablecer una contraseña

1. En el usuario, pulse **Enlace para nueva contraseña**.
2. Envíelo por un canal privado (el módulo no envía correos).
3. El enlace sirve **una vez**, caduca (`password_reset_timeout`, 3 días) y deja de valer si el usuario cambia su contraseña o inicia sesión.

## Personalizar el aspecto

`site_name` y `brand_color` en `AuthSettings`. Las páginas siguen el modo claro u oscuro del sistema.
