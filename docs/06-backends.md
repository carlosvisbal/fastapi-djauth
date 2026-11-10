# 6. Backends de autenticación

Permiten iniciar sesión contra otras fuentes (LDAP, Active Directory, otro sistema, otras credenciales como un PIN) y sumar permisos de varias.

```python
AuthSettings(authentication_backends=(
    "miapp.auth.LDAPBackend",          # primero, el directorio de la empresa
    "djauth.backends.ModelBackend",    # si no, usuario y contraseña locales
))
```

Acepta rutas `"paquete.modulo.Clase"`, clases o instancias.

## Cómo funciona

| Paso | Comportamiento |
|---|---|
| Iniciar sesión | Se prueba cada backend en orden. El primero que devuelve un usuario gana. |
| Un backend lanza `PermissionDeniedError` | Se detiene la búsqueda y el acceso se niega. |
| Un backend no acepta esas credenciales | Se salta (su `authenticate` no tiene esos parámetros). |
| Un backend falla (p. ej. LDAP sin red) | Se registra el error y se prueba el siguiente. |
| Sesión abierta | Recuerda qué backend autenticó al usuario y le pide el usuario con `get_user()`. |
| Se quita un backend de la configuración | Las sesiones que abrió dejan de valer. |
| Permisos | `user.has_perm()` suma lo que concede cada backend (`get_all_permissions`). |

## Incluidos

| Backend | Qué hace |
|---|---|
| `djauth.backends.ModelBackend` | Usuario y contraseña de la base, con grupos y permisos. Rechaza inactivos. (Por defecto.) |
| `djauth.backends.AllowAllUsersModelBackend` | Igual, pero deja entrar a usuarios inactivos. |

## Escribir uno: ejemplo LDAP / Active Directory

```python
# miapp/auth.py
from djauth import BaseBackend, PermissionDeniedError

class LDAPBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None):
        persona = mi_directorio.validar(username, password)    # su cliente LDAP (ldap3, etc.)
        if persona is None:
            return None                                         # no es suyo: se prueba el siguiente
        if persona.cuenta_bloqueada:
            raise PermissionDeniedError("Su cuenta está bloqueada en el directorio.")  # se detiene aquí
        # Copia local del usuario: se crea la primera vez y se actualiza en cada inicio de sesión.
        return self.kit.get_or_create_user(username, defaults={
            "email": persona.email, "first_name": persona.nombre, "last_name": persona.apellido,
        })

    def get_user(self, user_id):
        user = self.kit.get_user_row(user_id)
        return user if user is not None and user.is_active else None

    def get_group_permissions(self, user_obj):
        # Opcional: permisos según los grupos del directorio, sin asignarlos en la administración.
        return {"ventas.view_pedido"} if user_obj.username in mi_directorio.miembros("Ventas") else set()
```

- El usuario creado por `get_or_create_user` **no tiene contraseña local**: solo entra por ese backend.
- Grupos, permisos y administración funcionan igual para él.
- `request` trae `ip`, `user_agent` y `headers` del intento.

## Otras credenciales (PIN, tarjeta, código)

```python
class PinBackend(BaseBackend):
    def authenticate(self, request, pin=None):
        ...
kit.authenticate(pin="4321")   # solo lo prueban los backends que aceptan `pin`
```

## Métodos que puede sobrescribir

| Método | Devuelve |
|---|---|
| `authenticate(request, **credenciales)` | Fila del usuario o `None` |
| `get_user(user_id)` | Fila del usuario o `None` (cierra la sesión) |
| `get_user_permissions(user_obj)` | `set[str]` |
| `get_group_permissions(user_obj)` | `set[str]` |
| `get_all_permissions(user_obj)` | `set[str]` (por defecto, la unión de los dos anteriores) |

Ayudas disponibles en `self.kit`: `find_user_row(username)`, `get_user_row(id)`, `get_or_create_user(username, defaults=...)`, `rehash_password(id, password)`.
