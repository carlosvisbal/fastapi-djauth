"""Historial de cambios del usuario: solo cambios de sus datos, campo por campo."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import String, select
from sqlalchemy.orm import Mapped, mapped_column

from djauth import AuthKit, AuthSettings, ExtraField

PWD = "Clave-Segura-2026"


class Perfil:
    telefono: Mapped[str] = mapped_column(String(20), default="", info={"label": "Teléfono"})
    cedula: Mapped[str] = mapped_column(String(20), default="", info={"label": "Cédula", "sensitive": True})


def make(tmp_path, **overrides) -> tuple[TestClient, AuthKit]:
    settings = AuthSettings(
        database_url=f"sqlite:///{tmp_path / 'auth.sqlite3'}",
        password_iterations=1000,
        bootstrap_superuser=("admin", PWD, "admin@example.com"),
        user_mixin=Perfil,
        extra_fields=(ExtraField("sede", "Sede"), ExtraField("salario", "Salario", type="number", sensitive=True)),
        **overrides,
    )
    kit = AuthKit(settings).init()
    app = FastAPI()
    kit.install(app)
    return TestClient(app), kit


@pytest.fixture
def setup(tmp_path):
    client, kit = make(tmp_path)
    with client:
        assert client.post("/auth/api/login", json={"username": "admin", "password": PWD}).status_code == 200
        yield client, kit


def history(client, **params) -> list[dict]:
    res = client.get("/auth/api/user-history", params=params)
    assert res.status_code == 200, res.text
    return res.json()["items"]


def test_create_update_password_delete_are_recorded(setup):
    client, kit = setup
    group = kit.create_group("Operador")
    created = client.post(
        "/auth/api/users?reason=Ingreso a la empresa",
        json={"username": "ana", "password": PWD + "x", "email": "ana@empresa.com", "groups": [group["id"]]},
    ).json()
    uid = created["id"]

    res = client.patch(
        f"/auth/api/users/{uid}", params={"reason": "Ascenso"}, json={"first_name": "Ana", "is_staff": True, "groups": []}
    )
    assert res.status_code == 200
    client.post(f"/auth/api/users/{uid}/password", json={"password": "Otra-Clave-Segura-1"})
    assert client.delete(f"/auth/api/users/{uid}?reason=Retiro").status_code == 204

    items = history(client, user_id=uid)
    assert [h["action"] for h in items] == ["delete", "password", "update", "create"]
    delete, password, update, create = items

    assert create["changes"]["username"] == {"old": None, "new": "ana"}
    assert create["changes"]["groups"] == {"old": None, "new": ["Operador"]}
    assert create["changes"]["password"] == {"hidden": True}
    assert create["reason"] == "Ingreso a la empresa"

    # Solo lo que cambió, con el valor anterior y el nuevo.
    assert update["changes"] == {
        "first_name": {"old": "", "new": "Ana"},
        "is_staff": {"old": False, "new": True},
        "groups": {"old": ["Operador"], "new": []},
    }
    assert update["reason"] == "Ascenso"
    assert update["actor"] == "admin" and update["actor_id"] == 1
    assert update["ip"] == "testclient"

    assert password["changes"] == {"password": {"hidden": True}}
    assert password["reason"] == "Asignada por un administrador."

    # El historial sobrevive a la eliminación y guarda los últimos valores.
    assert delete["user"] == "ana" and delete["reason"] == "Retiro"
    assert delete["changes"]["email"] == {"old": "ana@empresa.com", "new": None}
    assert client.get(f"/auth/api/users/{uid}/history").json()["total"] == 4


def test_password_hash_never_reaches_the_history(setup):
    client, kit = setup
    uid = client.post("/auth/api/users", json={"username": "beto", "password": PWD + "y"}).json()["id"]
    client.post(f"/auth/api/users/{uid}/password", json={"password": "Otra-Clave-Segura-2"})
    with kit._db() as db:
        rows = db.scalars(select(kit.models.UserChange)).all()
        dumped = json.dumps([r.changes for r in rows])
        hashes = [u.password for u in db.scalars(select(kit.models.User))]
    assert "pbkdf2" not in dumped and all(h not in dumped for h in hashes)
    assert PWD not in dumped and "Otra-Clave" not in dumped


def test_only_user_changes_not_logins_or_noops(setup):
    client, _kit = setup
    uid = client.post("/auth/api/users", json={"username": "carla", "password": PWD + "z"}).json()["id"]
    before = len(history(client))
    # Iniciar sesión, cerrar sesiones o generar enlaces no son cambios del usuario.
    with TestClient(client.app) as other:
        assert other.post("/auth/api/login", json={"username": "carla", "password": PWD + "z"}).status_code == 200
    client.post(f"/auth/api/users/{uid}/logout")
    client.post(f"/auth/api/users/{uid}/reset-link")
    # Guardar sin cambiar nada tampoco.
    client.patch(f"/auth/api/users/{uid}", json={"username": "carla", "is_active": True})
    assert len(history(client)) == before
    # El registro general sí lo anota.
    actions = {e["action"] for e in client.get(f"/auth/api/log?object_type=user&object_id={uid}").json()["items"]}
    assert {"login", "logout_all", "reset_link"} <= actions


def test_custom_and_extra_fields_sensitive_values_are_hidden(setup):
    client, _kit = setup
    uid = client.post(
        "/auth/api/users",
        json={"username": "dora", "password": PWD + "w", "telefono": "300", "cedula": "123", "extra": {"sede": "Norte"}},
    ).json()["id"]
    client.patch(f"/auth/api/users/{uid}", json={"telefono": "301", "cedula": "999", "extra": {"sede": "Sur", "salario": 5000}})
    update = history(client, user_id=uid, action="update")[0]
    assert update["changes"]["telefono"] == {"old": "300", "new": "301"}
    assert update["changes"]["extra.sede"] == {"old": "Norte", "new": "Sur"}
    assert update["changes"]["cedula"] == {"hidden": True}
    assert update["changes"]["extra.salario"] == {"hidden": True}
    assert "999" not in json.dumps(update) and "5000" not in json.dumps(update)


def test_filters(setup):
    client, _kit = setup
    uid = client.post("/auth/api/users", json={"username": "eva", "password": PWD + "v"}).json()["id"]
    client.patch(f"/auth/api/users/{uid}", json={"email": "eva@empresa.com"})
    client.patch(f"/auth/api/users/{uid}", json={"first_name": "Eva"})
    assert [h["changes"] for h in history(client, user_id=uid, field="email")] == [
        {"email": {"old": "", "new": "eva@empresa.com"}}
    ]
    assert len(history(client, user_id=uid, action="update")) == 2
    assert len(history(client, actor_id=1, user_id=uid)) == 3
    # "_" no es comodín: "first_name" no debe coincidir con otro campo parecido.
    assert len(history(client, user_id=uid, field="first%")) == 0
    res = client.get("/auth/api/user-history?action=borrar")
    assert res.status_code == 422 and res.json()["code"] == "invalid_format"


def test_group_deletion_is_recorded_for_its_members(setup):
    client, kit = setup
    group = kit.create_group("Turno noche")
    uid = client.post("/auth/api/users", json={"username": "fabio", "password": PWD + "u", "groups": [group["id"]]}).json()["id"]
    assert client.delete(f"/auth/api/groups/{group['id']}").status_code == 204
    last = history(client, user_id=uid)[0]
    assert last["changes"] == {"groups": {"old": ["Turno noche"], "new": []}}
    assert last["reason"] == "Se eliminó el grupo Turno noche."


def test_self_service_and_reset_link_reasons(setup):
    client, kit = setup
    uid = client.post("/auth/api/users", json={"username": "gina", "password": PWD + "t"}).json()["id"]
    with TestClient(client.app) as gina:
        gina.post("/auth/api/login", json={"username": "gina", "password": PWD + "t"})
        res = gina.post("/auth/api/me/password", json={"old_password": PWD + "t", "new_password": "Nueva-Clave-Segura-3"})
        assert res.status_code == 200, res.text
    token = kit.make_reset_token(uid)
    kit.reset_password(uid, token, "Nueva-Clave-Segura-4")
    reasons = [h["reason"] for h in history(client, user_id=uid, action="password")]
    assert reasons == ["Restablecida con un enlace.", "Cambiada por el propio usuario."]


def test_history_requires_its_own_permission(setup):
    client, kit = setup
    kit.create_user("staff", PWD + "s", is_staff=True)
    viewer = kit.create_user("auditor", PWD + "a", is_staff=True)
    perm = next(p["id"] for p in kit.list_permissions() if p["key"] == "auth.view_userchange")
    kit.update_user(viewer["id"], {"permissions": [perm]})
    with TestClient(client.app) as other:
        other.post("/auth/api/login", json={"username": "staff", "password": PWD + "s"})
        res = other.get("/auth/api/user-history")
        assert res.status_code == 403 and "auth.view_userchange" in res.text
    with TestClient(client.app) as other:
        other.post("/auth/api/login", json={"username": "auditor", "password": PWD + "a"})
        assert other.get("/auth/api/user-history").status_code == 200
        assert other.get(f"/auth/api/users/{viewer['id']}/history").status_code == 200
    with TestClient(client.app) as anonymous:
        assert anonymous.get("/auth/api/user-history").status_code == 401


def test_history_can_be_disabled(tmp_path):
    _client, kit = make(tmp_path, user_history=False)
    kit.create_user("hugo", PWD + "h")
    assert kit.user_history() == ([], 0)


def test_programmatic_changes_without_request(setup):
    _client, kit = setup
    user = kit.create_user("ivan", PWD + "i", reason="Importado de nómina")
    kit.update_user(user["id"], {"last_name": "Ruiz"})
    items, total = kit.user_history(user["id"])
    assert total == 2
    assert items[0]["actor"] == "sistema" and items[0]["ip"] == ""
    assert items[1]["reason"] == "Importado de nómina"
