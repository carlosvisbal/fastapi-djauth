"""Decoradores con los nombres de Django: login_required, permission_required y compañía."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from djauth import (
    AuthKit,
    AuthSettings,
    AuthUser,
    current_user,
    login_required,
    permission_required,
    staff_member_required,
    superuser_required,
    user_passes_test,
)

PWD = "Clave-Segura-2026"


@pytest.fixture
def client(tmp_path):
    kit = AuthKit(
        AuthSettings(
            database_url=f"sqlite:///{tmp_path / 'auth.sqlite3'}",
            password_iterations=1000,
            bootstrap_superuser=("admin", PWD, ""),
            permissions={"ventas": {"view_pedido": "Ver pedidos", "aprobar_pedido": "Aprobar pedidos"}},
        )
    ).init()
    perms = {p["key"]: p["id"] for p in kit.list_permissions()}
    kit.create_user("vendedor", PWD, email="ana@empresa.com", permissions=[perms["ventas.view_pedido"]])
    kit.create_user("externo", PWD, email="x@gmail.com")
    kit.create_user("staff", PWD, is_staff=True)
    app = FastAPI()

    @app.get("/perfil")
    @login_required
    def perfil():
        return {"ok": True}

    @app.get("/pedidos/{pedido_id}")
    @permission_required("ventas.view_pedido")
    async def pedido(pedido_id: int, detalle: bool = False):  # async, con parámetros de ruta y de consulta
        return {"id": pedido_id, "detalle": detalle}

    @app.post("/pedidos/{pedido_id}/aprobar")
    @permission_required("ventas.view_pedido", "ventas.aprobar_pedido")
    def aprobar(pedido_id: int):
        return {"aprobado": pedido_id}

    @app.get("/yo")
    @login_required
    def yo(user: AuthUser = Depends(current_user)):  # la función puede pedir el usuario como siempre
        return {"user": user.username}

    @app.get("/interno")
    @staff_member_required
    def interno():
        return {"ok": True}

    @app.get("/root")
    @superuser_required
    def root():
        return {"ok": True}

    @app.get("/empresa")
    @user_passes_test(lambda u: u.email.endswith("@empresa.com"), "Solo cuentas de la empresa.", code="company_only")
    def empresa():
        return {"ok": True}

    @app.get("/doble")
    @login_required
    @permission_required("ventas.view_pedido")
    def doble():
        return {"ok": True}

    kit.install(app)
    with TestClient(app) as c:
        yield c


def as_user(client, username):
    client.cookies.clear()
    assert client.post("/auth/api/login", json={"username": username, "password": PWD}).status_code == 200


def test_login_required(client):
    res = client.get("/perfil")
    assert res.status_code == 401 and res.json()["code"] == "not_authenticated"
    as_user(client, "externo")
    assert client.get("/perfil").json() == {"ok": True}
    assert client.get("/yo").json() == {"user": "externo"}


def test_permission_required_keeps_route_parameters(client):
    assert client.get("/pedidos/7").status_code == 401
    as_user(client, "externo")
    denied = client.get("/pedidos/7").json()
    assert denied["code"] == "missing_permission" and "ventas.view_pedido" in denied["detail"]
    as_user(client, "vendedor")
    assert client.get("/pedidos/7?detalle=true").json() == {"id": 7, "detalle": True}
    # Requiere los dos permisos: el vendedor solo tiene uno.
    res = client.post("/pedidos/7/aprobar", headers={"Origin": "http://testserver"}).json()
    assert "ventas.aprobar_pedido" in res["detail"]
    as_user(client, "admin")
    assert client.post("/pedidos/7/aprobar", headers={"Origin": "http://testserver"}).json() == {"aprobado": 7}


def test_staff_superuser_and_custom_tests(client):
    as_user(client, "vendedor")
    assert client.get("/interno").json()["code"] == "staff_required"
    assert client.get("/root").json()["code"] == "superuser_required"
    assert client.get("/empresa").json() == {"ok": True}
    as_user(client, "externo")
    res = client.get("/empresa").json()
    assert res["code"] == "company_only" and res["detail"] == "Solo cuentas de la empresa."
    as_user(client, "staff")
    assert client.get("/interno").json() == {"ok": True}


def test_stacked_decorators(client):
    as_user(client, "externo")
    assert client.get("/doble").status_code == 403
    as_user(client, "vendedor")
    assert client.get("/doble").json() == {"ok": True}


def test_decorators_do_not_leak_into_openapi_parameters(client):
    params = client.get("/openapi.json").json()["paths"]["/pedidos/{pedido_id}"]["get"]["parameters"]
    assert {p["name"] for p in params} == {"pedido_id", "detalle"}


def test_misuse_gives_a_clear_error():
    with pytest.raises(TypeError, match=r"app\.codename"):
        permission_required("sin_punto")
    with pytest.raises(TypeError, match=r"app\.codename"):
        permission_required()
