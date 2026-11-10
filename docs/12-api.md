# 12. API REST

Todas bajo `/auth/api` (o el prefijo que pase a `install`). La documentación interactiva queda en `/docs` de su aplicación, en la sección **auth**.

## Acceso

| Método | Ruta | Cuerpo | Respuesta |
|---|---|---|---|
| POST | `/login` | `{"username", "password"}` | `{"user"}` + cookie de sesión |
| POST | `/token` | `{"username", "password"}` o formulario OAuth2 | `{"access_token", "token_type", "expires_in", "user"}` |
| POST | `/logout` | — | Cierra la sesión o revoca el token presentado |
| GET | `/config` | — | Nombre del sitio, tipos de autenticación activos, campos propios, ayudas de contraseña |
| POST | `/reset/confirm` | `{"uid", "token", "new_password"}` | Fija la contraseña con un enlace |

## Mi cuenta (cualquier usuario con sesión)

| Método | Ruta | Para |
|---|---|---|
| GET | `/me` | Mis datos, grupos y permisos efectivos |
| PATCH | `/me` | `{"email", "first_name", "last_name"}` |
| POST | `/me/password` | `{"old_password", "new_password"}` (cierra mis otras sesiones) |

## Administración (personal con el permiso indicado)

| Método | Ruta | Permiso | Para |
|---|---|---|---|
| GET | `/users?q=&is_active=&is_staff=&is_superuser=&group=&order=&limit=&offset=` | `auth.view_user` | Listar |
| POST | `/users` | `auth.add_user` | Crear |
| GET | `/users/{id}` | `auth.view_user` | Detalle (con sesiones activas) |
| PATCH | `/users/{id}` | `auth.change_user` | Modificar (solo los campos enviados) |
| DELETE | `/users/{id}` | `auth.delete_user` | Eliminar |
| POST | `/users/{id}/password` | `auth.change_user` | `{"password"}` |
| POST | `/users/{id}/reset-link` | `auth.change_user` | `{"url", "token", "expires_in"}` |
| POST | `/users/{id}/logout` | `auth.change_user` | Cerrar todas sus sesiones y tokens |
| GET, POST | `/groups` | `auth.view_group` / `auth.add_group` | Listar / crear `{"name", "permissions": [ids]}` |
| GET, PATCH, DELETE | `/groups/{id}` | `auth.view_group` / `change_group` / `delete_group` | Grupo |
| GET | `/permissions` | personal | Permisos disponibles (con su `id`) |
| GET | `/log?object_type=&object_id=&limit=&offset=` | `auth.view_logentry` | Registro de acciones |

### Usuario (respuesta)

```json
{
  "id": 3, "username": "ana", "email": "ana@example.com", "first_name": "Ana", "last_name": "Pérez",
  "full_name": "Ana Pérez", "is_active": true, "is_staff": false, "is_superuser": false,
  "last_login": "2026-11-10T08:15:00", "date_joined": "2026-11-01T10:00:00",
  "groups": ["Vendedor"], "permissions": ["ventas.view_pedido"], "extra": {},
  "group_ids": [2], "permission_ids": [], "has_usable_password": true,
  "telefono": "+1 555 0100"
}
```

Las columnas propias (`user_mixin`) van en el primer nivel; los campos JSON, en `extra`. Al crear o modificar se envían igual. Una clave desconocida responde `400` con `errors`.

Errores: ver [Errores](09-errores.md).
