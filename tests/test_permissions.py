"""Permisos propios creados desde la administración (como agregar un `Permission` en Django)."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from djauth import AuthKit, AuthSettings
from djauth.errors import PermissionDeniedError, ValidationError

PWD = "Clave-Segura-2026"


@pytest.fixture
def setup(tmp_path):
    kit = AuthKit(
        AuthSettings(
            database_url=f"sqlite:///{tmp_path / 'auth.sqlite3'}",
            password_iterations=1000,
            bootstrap_superuser=("admin", PWD, "admin@example.com"),
            permissions={"ventas": {"view_pedido": "Puede ver pedidos", "aprobar_pedido": "Puede aprobar pedidos"}},
        )
    ).init()
    app = FastAPI()
    kit.install(app)
    with TestClient(app) as client:
        yield client, kit


def login(client, username="admin", password=PWD):
    res = client.post("/auth/api/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text


def perm_ids(kit) -> dict[str, int]:
    return {p["key"]: p["id"] for p in kit.list_permissions()}


def test_superuser_creates_lists_renames_and_deletes_a_permission(setup):
    client, kit = setup
    login(client)
    res = client.post(
        "/auth/api/permissions", json={"app_label": "ventas", "codename": "aprobar_descuento", "name": "Puede aprobar descuentos"}
    )
    assert res.status_code == 201, res.text
    perm = res.json()
    assert perm["key"] == "ventas.aprobar_descuento" and perm["declared"] is False

    items = {p["key"]: p for p in client.get("/auth/api/permissions").json()["items"]}
    assert items["ventas.aprobar_descuento"]["declared"] is False
    assert items["ventas.aprobar_pedido"]["declared"] is True  # lo declara el código
    assert items["auth.add_permission"]["declared"] is True

    res = client.patch(f"/auth/api/permissions/{perm['id']}", json={"name": "Aprueba descuentos"})
    assert res.status_code == 200 and res.json()["name"] == "Aprueba descuentos"
    assert client.get(f"/auth/api/permissions/{perm['id']}").json()["name"] == "Aprueba descuentos"

    assert client.delete(f"/auth/api/permissions/{perm['id']}").status_code == 204
    assert client.get(f"/auth/api/permissions/{perm['id']}").status_code == 404
    log = [e["message"] for e in kit.list_log(object_type="permission")[0]]
    assert any("creado" in m for m in log) and any("eliminado" in m for m in log)


def test_a_created_permission_is_granted_like_a_declared_one(setup):
    _, kit = setup
    created = kit.create_permission("ventas", "exportar", "Puede exportar")
    kit.create_user("ana", PWD)
    ana = kit.get_by_username("ana")
    assert not ana.has_perm("ventas.exportar")
    kit.update_user(ana.id, {"permissions": [created["id"]]})
    assert kit.get_by_username("ana").has_perm("ventas.exportar")


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"app_label": "Ventas", "codename": "x", "name": "X"}, "app_label"),
        ({"app_label": "ventas", "codename": "con espacio", "name": "X"}, "codename"),
        ({"app_label": "ventas", "codename": "1x", "name": "X"}, "codename"),
        ({"app_label": "ventas", "codename": "x", "name": "   "}, "name"),
        ({"app_label": "auth", "codename": "superpoder", "name": "X"}, "app_label"),
        ({"app_label": "sessions", "codename": "x", "name": "X"}, "app_label"),
        ({"app_label": "ventas", "codename": "aprobar_pedido", "name": "Repetido"}, "codename"),
    ],
)
def test_invalid_reserved_or_repeated_permissions_are_rejected(setup, body, field):
    client, _ = setup
    login(client)
    res = client.post("/auth/api/permissions", json=body)
    assert res.status_code == 400, res.text
    assert field in res.json()["errors"]


def test_permissions_declared_in_code_cannot_be_changed_or_deleted(setup):
    client, kit = setup
    login(client)
    ids = perm_ids(kit)
    for key in ("ventas.aprobar_pedido", "auth.change_user"):
        assert client.patch(f"/auth/api/permissions/{ids[key]}", json={"name": "Otro"}).status_code == 403
        res = client.delete(f"/auth/api/permissions/{ids[key]}")
        assert res.status_code == 403 and res.json()["code"] == "declared_permission"
    with pytest.raises(PermissionDeniedError):
        kit.delete_permission(ids["auth.delete_user"])
    assert "ventas.aprobar_pedido" in perm_ids(kit)


def test_managing_permissions_requires_its_own_permissions(setup):
    client, kit = setup
    ids = perm_ids(kit)
    kit.create_user("rrhh", PWD, is_staff=True, permissions=[ids["auth.view_user"]])
    login(client, "rrhh", PWD)
    assert client.get("/auth/api/permissions").status_code == 200
    body = {"app_label": "ventas", "codename": "nuevo", "name": "Nuevo"}
    assert client.post("/auth/api/permissions", json=body).status_code == 403
    created = kit.create_permission("ventas", "otro", "Otro")
    assert client.patch(f"/auth/api/permissions/{created['id']}", json={"name": "X"}).status_code == 403
    assert client.delete(f"/auth/api/permissions/{created['id']}").status_code == 403


def test_creating_a_permission_does_not_let_staff_grant_it(setup):
    """Quien crea un permiso no lo recibe: asignarlo sigue exigiendo tenerlo (o ser superusuario)."""
    client, kit = setup
    ids = perm_ids(kit)
    staff_perms = [ids[k] for k in ("auth.add_permission", "auth.view_group", "auth.add_group", "auth.change_group")]
    kit.create_user("jefe", PWD, is_staff=True, permissions=staff_perms)
    login(client, "jefe", PWD)
    created = client.post("/auth/api/permissions", json={"app_label": "ventas", "codename": "anular", "name": "Anular"})
    assert created.status_code == 201
    res = client.post("/auth/api/groups", json={"name": "Mio", "permissions": [created.json()["id"]]})
    assert res.status_code == 403
    me = client.get("/auth/api/me").json()
    assert "ventas.anular" not in me["permissions"]


def test_deleting_a_permission_removes_it_from_groups_and_users_with_history(setup):
    _, kit = setup
    perm = kit.create_permission("ventas", "anular", "Anular")
    group = kit.create_group("Caja", [perm["id"]])
    kit.create_user("ana", PWD, permissions=[perm["id"]])
    kit.create_user("luis", PWD, groups=[group["id"]])
    assert kit.get_by_username("luis").has_perm("ventas.anular")

    kit.delete_permission(perm["id"])

    assert not kit.get_by_username("ana").has_perm("ventas.anular")
    assert not kit.get_by_username("luis").has_perm("ventas.anular")
    assert kit.get_group(group["id"])["permissions"] == []
    changes, _ = kit.user_history(kit.get_by_username("ana").id, action="update")
    assert changes[0]["changes"]["permissions"] == {"old": ["ventas.anular"], "new": []}
    assert "Caja" in kit.list_log(object_type="permission")[0][0]["message"]

    # Un permiso nuevo con el mismo id no hereda a quienes tenían el eliminado.
    again = kit.create_permission("ventas", "otro", "Otro")
    assert not kit.get_by_username("ana").has_perm(f"ventas.{again['codename']}")
    assert kit.get_group(group["id"])["permissions"] == []


def test_a_deleted_group_does_not_pass_its_members_to_the_next_group(setup):
    """Regresión: en SQLite, borrar un grupo dejaba a sus miembros apuntando a un id que el siguiente
    grupo reutilizaba, y heredaban sus permisos."""
    _, kit = setup
    ids = perm_ids(kit)
    group = kit.create_group("Temporal", [ids["ventas.view_pedido"]])
    kit.create_user("ana", PWD, groups=[group["id"]])
    kit.delete_group(group["id"])
    kit.create_group("Aprobadores", [ids["ventas.aprobar_pedido"]])
    ana = kit.get_by_username("ana")
    assert ana.groups == () and not ana.has_perm("ventas.aprobar_pedido")


def test_sqlite_enforces_foreign_keys(setup):
    _, kit = setup
    with kit.engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_orphan_rows_from_older_versions_are_purged_on_start(tmp_path):
    db = tmp_path / "auth.sqlite3"
    settings = AuthSettings(database_url=f"sqlite:///{db}", password_iterations=1000, permissions={"ventas": {"x": "X"}})
    kit = AuthKit(settings).init()
    kit.create_user("ana", PWD)
    user_id = kit.get_by_username("ana").id
    kit.engine.dispose()
    # Lo que dejaba una versión anterior: membresía en un grupo (id 99) que ya no existe.
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO auth_user_groups (user_id, group_id) VALUES (?, 99)", (user_id,))
    AuthKit(settings).init()
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM auth_user_groups").fetchone()[0] == 0


def test_update_permission_validates_the_name(setup):
    _, kit = setup
    perm = kit.create_permission("ventas", "anular", "Anular")
    with pytest.raises(ValidationError):
        kit.update_permission(perm["id"], {"name": ""})
