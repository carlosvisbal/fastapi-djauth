# 5. Usuarios, grupos y permisos

Un **permiso** es `app.codename`; un **grupo** (rol) reúne permisos; un usuario recibe los permisos de sus grupos más los que se le asignen directamente. Un **superusuario** los tiene todos.

## Iniciar sesión con usuario o con correo

Un proyecto usa **uno u otro**, no los dos.

```python
AuthSettings(username_field="username")   # por defecto: se entra con el nombre de usuario
AuthSettings(username_field="email")      # se entra con el correo
```

| | `"username"` | `"email"` |
|---|---|---|
| Se escribe para entrar | El usuario (`ana`) | El correo (`ana@empresa.com`) |
| Obligatorio y único | `username` | `email`, sin distinguir mayúsculas (la base lo garantiza en SQLite y PostgreSQL) |
| El otro campo | El correo es opcional | `username` se mantiene igual al correo (no se edita) |
| Crear por API | `{"username": "ana", "password": …}` | `{"email": "ana@empresa.com", "password": …}` |
| Iniciar sesión | `{"username": "ana", …}` | `{"username": "ana@empresa.com", …}` o `{"email": …}` |

Las páginas se adaptan solas (la de inicio de sesión pide "Correo"). Si necesita aceptar los dos, escriba un [backend](06-backends.md) que busque por uno u otro.

> Cambiar a `"email"` en una base que ya tiene usuarios: revise que no haya correos repetidos ni vacíos antes; el módulo avisa en el log si no puede crear el índice único.

## Declarar los permisos del proyecto

```python
AuthSettings(permissions={
    "ventas": {"view_pedido": "Puede ver pedidos", "aprobar_pedido": "Puede aprobar pedidos"},
    "inventario": {"ajustar_stock": "Puede ajustar el stock"},
})
# o después:
kit.register_permissions("informes", {"exportar": "Puede exportar informes"})
```

Aparecen solos en la administración. Cambiar la descripción en el código la actualiza al arrancar.

## Crear permisos desde la administración

Como agregar un `Permission` en Django: en la pestaña **Permisos** (o `POST /auth/api/permissions`) se crean permisos propios sin tocar el código, por ejemplo para una regla nueva (`rule(r"^/informes", "informes.exportar")`) o para que la interfaz muestre u oculte algo según `user.has_perm(...)`.

```python
kit.create_permission("informes", "exportar", "Puede exportar informes")   # devuelve {"id", "key", …}
kit.update_permission(perm_id, {"name": "Puede exportar informes en Excel"})
kit.delete_permission(perm_id)
```

Reglas que se cumplen siempre:

- `app_label` y `codename` usan minúsculas, números y guion bajo, empezando por una letra. Las aplicaciones de djauth (`auth`, `sessions`, `admin`) están reservadas.
- Los permisos que declara el código (los de djauth y los de `permissions=` o `register_permissions`) aparecen como **Código**: no se renombran ni se eliminan desde la administración, porque la aplicación los vuelve a crear al arrancar. Los demás aparecen como **Propio**.
- El código (`app.codename`) no cambia después de creado, porque las rutas lo usan por ese nombre. Solo se edita la descripción.
- Crear un permiso no lo concede a nadie. Para asignarlo a un grupo o a un usuario hay que tenerlo o ser superusuario, así que crear permisos no sirve para darse privilegios.
- Al eliminarlo, los grupos y usuarios que lo tenían lo pierden. Queda en el registro de acciones (con los grupos afectados) y en el historial de cada usuario que lo tenía asignado directamente.

Requieren `auth.add_permission`, `auth.change_permission` y `auth.delete_permission`.

## Crear roles iniciales

```python
kit.ensure_group("Vendedor", ["ventas.view_pedido"])
kit.ensure_group("Jefe de ventas", ["ventas.view_pedido", "ventas.aprobar_pedido"])
```

`ensure_group` solo crea el grupo si no existe: lo que luego se ajuste en la administración no se pisa al reiniciar.

## Usar permisos

```python
@app.post("/pedidos/{id}/aprobar")
def aprobar(id: int, user: AuthUser = Depends(require_perm("ventas.aprobar_pedido"))): ...

if user.has_perm("inventario.ajustar_stock"): ...
```

## Desde código (scripts, importaciones, pruebas)

El núcleo no depende de FastAPI:

```python
kit.create_user("ana", "Clave-Segura-2026", email="ana@example.com", groups=[vendedor_id])
kit.create_superuser("root", "Otra-Clave-Segura-1")
kit.update_user(user_id, {"is_active": False})          # también cierra sus sesiones
kit.set_password(user_id, "Nueva-Clave-2026")           # cierra sus otras sesiones
kit.authenticate("ana", "Clave-Segura-2026")            # AuthUser o InvalidCredentialsError
kit.get_by_username("ana")                              # AuthUser o None
users, total = kit.list_users(q="ana", is_active=True, limit=50)
kit.list_groups(); kit.create_group("Bodega", [perm_id]); kit.list_permissions()
link_token = kit.make_reset_token(user_id)              # para enviar un enlace de restablecimiento
```

## Reglas que el módulo hace cumplir

- Un administrador que no es superusuario **no puede**: crear o modificar superusuarios, conceder permisos que él no tiene, ni modificar (o cambiar la contraseña de) usuarios con permisos que él no tiene.
- Siempre queda al menos un superusuario activo.
- Nadie puede desactivarse ni eliminarse a sí mismo.
- Desactivar a un usuario cierra todas sus sesiones y tokens. Prefiéralo a eliminarlo: conserva el registro.

## Permisos de la administración

`auth.view_user`, `auth.add_user`, `auth.change_user`, `auth.delete_user`, `auth.view_group`, `auth.add_group`, `auth.change_group`, `auth.delete_group`, `auth.view_permission`, `auth.add_permission`, `auth.change_permission`, `auth.delete_permission`, `auth.view_logentry`, `auth.view_userchange`. Para entrar a la administración hace falta además **"Acceso a la administración"** (`is_staff`).
