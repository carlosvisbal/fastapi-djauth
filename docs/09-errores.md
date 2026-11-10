# 9. Errores

Todas las respuestas de error tienen la misma forma, también en las rutas de su aplicación que usen las dependencias del módulo:

```json
{
  "detail": "No tiene permiso para esta acción. Requiere: ventas.aprobar_pedido.",
  "code": "missing_permission",
  "hint": "Pida a un administrador ese permiso o un rol (grupo) que lo incluya.",
  "errors": {}
}
```

| Clave | Para |
|---|---|
| `detail` | Mensaje para mostrar a la persona. |
| `code` | Identificador fijo: úselo en su código, no el texto. |
| `hint` | Qué hacer para resolverlo (puede venir vacío). |
| `errors` | Errores por campo: `{"campo": ["mensaje", …]}`. Los generales van en `"__all__"`. |
| `retry_after` | Solo en `too_many_attempts`: segundos de espera (también en la cabecera `Retry-After`). |

## Códigos

| HTTP | `code` | Cuándo |
|---|---|---|
| 400 | `validation_error` | Datos no válidos según las reglas (usuario repetido, contraseña débil…). Ver `errors`. |
| 400 | `username_taken` / `email_taken` | Ya existe un usuario con ese nombre o correo. |
| 400 | `last_superuser` | Se intentó dejar el sistema sin superusuarios activos. |
| 400 | `self_delete` | Un usuario intentó eliminarse a sí mismo. |
| 400 | `invalid_reset_link` | Enlace de restablecimiento no válido, usado o caducado. |
| 400 | `payload_too_large` | Petición de token demasiado grande. |
| 400 | `service_account` | Se intentó cambiar perfil o contraseña de una llave de API. |
| 401 | `not_authenticated` | Sin sesión, sesión caducada o token inválido. |
| 401 | `invalid_credentials` | Usuario o contraseña incorrectos (mismo mensaje en ambos casos, a propósito). |
| 403 | `permission_denied` | Acción no permitida (genérico). |
| 403 | `missing_permission` | Falta un permiso concreto; `detail` dice cuál. |
| 403 | `staff_required` | La acción es solo para personal de administración. |
| 403 | `superuser_required` | La acción es solo para superusuarios. |
| 403 | `target_has_more_permissions` | Un administrador intentó modificar a alguien con más permisos que él. |
| 403 | `csrf_failed` | Petición con cookie que llegó desde otro sitio. |
| 403 | `sessions_disabled` / `bearer_disabled` | Ese tipo de autenticación está desactivado. |
| 404 | `not_found` | El usuario o grupo no existe. |
| 422 | `invalid_format` | Formato incorrecto (tipo, longitud, campo faltante); `errors` dice qué campo. |
| 429 | `too_many_attempts` | Bloqueo temporal tras varios intentos fallidos. |
| — | `database_config` | Al arrancar: la configuración de `database` es incorrecta (lanza `DatabaseConfigError` con la pista). |

Un backend propio puede lanzar sus propios códigos: `PermissionDeniedError("Fuera de horario.", code="outside_hours", hint="…")`.

## En Python

```python
from djauth import AuthError, InvalidCredentialsError, ValidationError

try:
    kit.create_user("ana", "123")
except ValidationError as e:
    e.code      # "validation_error"
    e.errors    # {"password": ["La contraseña es muy corta…", "La contraseña no puede ser solo números."]}
    e.hint
```

Todas heredan de `AuthError` (`code`, `message`, `hint`, `status`, `to_dict()`).

## En el navegador o una app

```js
const res = await fetch("/auth/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body });
if (!res.ok) {
  const err = await res.json();
  if (err.code === "too_many_attempts") esperar(err.retry_after);
  else mostrar(err.detail, err.hint, err.errors);
}
```

## WebSocket

Al rechazar un WebSocket, el motivo del cierre (código 1008) es `"<code>: <detail>"`.
