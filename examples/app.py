"""Ejemplo mínimo: `uvicorn examples.app:app --reload` y abra http://localhost:8000/auth/admin

Usuario inicial: admin / Cambiar-Esta-Clave-1 (cámbiela en "Mi cuenta").
"""

from fastapi import Depends, FastAPI

from djauth import AuthKit, AuthSettings, AuthUser, current_user, require_perm, rule

kit = AuthKit(
    AuthSettings(
        database_url="sqlite:///./auth.sqlite3",
        site_name="Mi empresa",
        home_url="/",
        bootstrap_superuser=("admin", "Cambiar-Esta-Clave-1", "admin@example.com"),
        permissions={"ventas": {"view_pedido": "Puede ver pedidos", "aprobar_pedido": "Puede aprobar pedidos"}},
    )
).init()
kit.ensure_group("Vendedor", ["ventas.view_pedido"])
kit.ensure_group("Jefe de ventas", ["ventas.view_pedido", "ventas.aprobar_pedido"])

app = FastAPI(title="Ejemplo djauth")


@app.get("/")
def inicio(user: AuthUser = Depends(current_user)):
    return {"hola": user.get_full_name() or user.username, "permisos": sorted(user.permissions)}


@app.get("/pedidos")
def pedidos(user: AuthUser = Depends(require_perm("ventas.view_pedido"))):
    return [{"id": 1, "cliente": "ACME", "estado": "pendiente"}]


@app.post("/pedidos/{pedido_id}/aprobar")
def aprobar(pedido_id: int, user: AuthUser = Depends(require_perm("ventas.aprobar_pedido"))):
    return {"id": pedido_id, "aprobado_por": user.username}


# protect=True exige sesión o token en TODA la app; `rules` añade permisos por ruta sin tocar cada función.
kit.install(app, protect=True, rules=[rule(r"^/pedidos", "ventas.view_pedido")])
