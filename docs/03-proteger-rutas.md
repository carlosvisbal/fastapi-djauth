# 3. Proteger rutas

## Por ruta, con dependencias

```python
from fastapi import Depends
from djauth import AuthUser, current_user, optional_user, require_perm, require_staff, require_superuser

@app.get("/perfil")
def perfil(user: AuthUser = Depends(current_user)):          # @login_required
    return user.to_dict()

@app.post("/pedidos/{id}/aprobar")
def aprobar(id: int, user: AuthUser = Depends(require_perm("ventas.aprobar_pedido"))):  # @permission_required
    ...

@app.get("/informes")
def informes(user: AuthUser = Depends(require_perm("ventas.view_pedido", "ventas.view_cliente"))):  # todos
    ...

@app.get("/reportes-internos")
def internos(user: AuthUser = Depends(require_staff)):        # @staff_member_required
    ...

@app.get("/inicio")
def inicio(user: AuthUser | None = Depends(optional_user)):   # público, pero sabe si hay sesión
    return {"saludo": f"Hola {user.username}" if user else "Hola visitante"}
```

| Sin sesión | Sin el permiso |
|---|---|
| `401` con `code: "not_authenticated"` | `403` con `code: "missing_permission"` y el permiso que falta |

## Con decoradores

Los mismos controles, escritos como decoradores. Van **debajo** de `@app.get(...)`:

```python
from djauth import login_required, permission_required, staff_member_required, superuser_required, user_passes_test

@app.get("/perfil")
@login_required
def perfil(): ...

@app.post("/pedidos/{id}/aprobar")
@permission_required("ventas.aprobar_pedido")          # varios: ("ventas.view_pedido", "ventas.change_pedido")
async def aprobar(id: int): ...

@app.get("/reportes-internos")
@staff_member_required
def internos(): ...

@app.get("/mantenimiento")
@superuser_required
def mantenimiento(): ...

@app.get("/solo-empresa")
@user_passes_test(lambda u: u.email.endswith("@empresa.com"), "Solo cuentas de la empresa.")
def solo_empresa(): ...
```

Se comportan igual que las dependencias (mismos errores, aparecen en `/docs`) y se pueden apilar. Si la función necesita al usuario, pídalo con `user: AuthUser = Depends(current_user)`.

| Decorador | Dependencia equivalente |
|---|---|
| `@login_required` | `Depends(current_user)` |
| `@permission_required("a.b")` | `Depends(require_perm("a.b"))` |
| `@staff_member_required` | `Depends(require_staff)` |
| `@superuser_required` | `Depends(require_superuser)` |
| `@user_passes_test(test)` | — |

## Toda la aplicación a la vez

```python
from djauth import rule

kit.install(
    app,
    protect=True,                                   # todo exige sesión o token
    exempt={"/health"},                             # rutas públicas exactas
    exempt_prefixes=("/public/", "/static/"),       # rutas públicas por prefijo
    rules=[
        rule(r"^/pedidos", "ventas.view_pedido", methods=["GET"]),
        rule(r"^/pedidos", "ventas.change_pedido"),   # el resto de métodos
        rule(r"^/admin-interno", "auth.view_user"),
    ],
)
```

- Gana la **primera** regla que coincide. Una ruta sin regla solo exige haber iniciado sesión.
- `pattern` es una expresión regular sobre la ruta. `methods` limita a esos métodos (un WebSocket cuenta como `WEBSOCKET`).
- Un navegador sin sesión se redirige a `/auth/login?next=...`; una API recibe `401`.
- Las páginas de acceso (`/auth/login`, `/auth/reset`) y la API de inicio de sesión quedan públicas solas.

## WebSocket

```python
from djauth import ws_user

@app.websocket("/ws")
async def ws(websocket: WebSocket):
    user = ws_user(websocket)          # cookie de sesión o ?access_token=<token Bearer>
    if user is None:
        await websocket.close(code=1008)
        return
    await websocket.accept()
```

Con `protect=True` el middleware ya rechaza los WebSocket sin credenciales.

## Llave de máquina

```python
kit.install(app, protect=True, api_key=os.environ["API_KEY"])
```

Un sistema externo envía `X-API-Key: <llave>` o `Authorization: Bearer <llave>` y tiene acceso total. Para accesos limitados, cree un usuario con su rol y use un token Bearer.

## El usuario autenticado

`AuthUser` tiene estos atributos y métodos:

```python
user.username, user.email, user.first_name, user.is_staff, user.is_superuser, user.groups
user.has_perm("ventas.aprobar_pedido")
user.has_perms(["ventas.view_pedido", "ventas.change_pedido"])
user.has_module_perms("ventas")
user.get_full_name()
user.backend          # backend que lo autenticó
user.telefono         # columnas propias (user_mixin)
```
