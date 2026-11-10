"""Backends de autenticación, columnas propias del usuario y errores descriptivos."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, Date, Integer, String, create_engine, inspect
from sqlalchemy.orm import Mapped, mapped_column

from djauth import (
    AuthKit,
    AuthSettings,
    AuthUser,
    BaseBackend,
    ModelBackend,
    PermissionDeniedError,
    current_user,
    require_perm,
)

PWD = "Clave-Segura-2026"
DIRECTORIO = {"ana.ldap": ("Clave-Del-Directorio-1", "Ana", "Pérez")}


class FakeLDAPBackend(BaseBackend):
    """Valida contra un "directorio" externo y mantiene la copia local del usuario."""

    def authenticate(self, request, username=None, password=None, **credentials):
        entry = DIRECTORIO.get(username or "")
        if entry is None or entry[0] != password:
            return None
        return self.kit.get_or_create_user(username, defaults={"first_name": entry[1], "last_name": entry[2]})

    def get_user(self, user_id):
        user = self.kit.get_user_row(user_id)
        return user if user is not None and user.is_active else None

    def get_group_permissions(self, user_obj):
        # El directorio concede un permiso a todos sus usuarios, sin asignarlo en la administración.
        return {"ventas.view_pedido"} if user_obj.username in DIRECTORIO else set()


class BlockedHoursBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None, **credentials):
        if username == "nocturno":
            raise PermissionDeniedError("Fuera del horario permitido.", code="outside_hours")
        return None


class BrokenBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None, **credentials):
        raise ConnectionError("servidor LDAP sin red")


class PinBackend(BaseBackend):
    """Acepta otro tipo de credencial (un PIN): no recibe las de usuario y contraseña."""

    def authenticate(self, request, pin=None):
        return self.kit.find_user_row("admin") if pin == "4321" else None

    def get_user(self, user_id):
        return self.kit.get_user_row(user_id)


class Perfil:
    """Columnas propias del usuario (como heredar de AbstractUser en Django)."""

    telefono: Mapped[str] = mapped_column(String(20), default="", info={"label": "Teléfono", "help_text": "Con indicativo"})
    sede: Mapped[str | None] = mapped_column(
        String(30), nullable=True, info={"label": "Sede", "choices": ["Norte", "Sur"]}
    )
    turno: Mapped[int | None] = mapped_column(Integer, nullable=True)
    es_supervisor: Mapped[bool] = mapped_column(Boolean, default=False)
    ingreso: Mapped[date | None] = mapped_column(Date, nullable=True)
    codigo_sap: Mapped[str | None] = mapped_column(String(20), nullable=True, info={"editable": False})


def make(tmp_path, **overrides):
    settings = {
        "database_url": f"sqlite:///{tmp_path / 'auth.sqlite3'}",
        "password_iterations": 1000,
        "bootstrap_superuser": ("admin", PWD, ""),
        "permissions": {"ventas": {"view_pedido": "Puede ver pedidos"}},
        **overrides,
    }
    kit = AuthKit(AuthSettings(**settings)).init()
    app = FastAPI()

    @app.get("/pedidos")
    def pedidos(user: AuthUser = Depends(require_perm("ventas.view_pedido"))):
        return {"user": user.username, "backend": user.backend}

    @app.get("/yo")
    def yo(user: AuthUser = Depends(current_user)):
        return {"user": user.username}

    kit.install(app)
    return TestClient(app), kit


def login(client, username, password):
    return client.post("/auth/api/login", json={"username": username, "password": password})


# ---------------------------------------------------------------------- backends
def test_default_is_model_backend(tmp_path):
    _client, kit = make(tmp_path)
    assert [path for path, _ in kit.backends] == ["djauth.backends.ModelBackend"]
    assert kit.authenticate("admin", PWD).backend == "djauth.backends.ModelBackend"


def test_external_backend_creates_local_user_and_grants_permissions(tmp_path):
    backends = (f"{__name__}.FakeLDAPBackend", "djauth.backends.ModelBackend")
    client, kit = make(tmp_path, authentication_backends=backends)
    assert login(client, "ana.ldap", "Clave-Del-Directorio-1").status_code == 200
    me = client.get("/auth/api/me").json()
    assert (me["first_name"], me["last_name"]) == ("Ana", "Pérez")
    # Permiso concedido por el backend, sin asignarlo en la administración (suma de backends).
    assert client.get("/pedidos").json() == {"user": "ana.ldap", "backend": f"{__name__}.FakeLDAPBackend"}
    # La copia local no tiene contraseña: solo puede entrar por el directorio.
    assert kit.get_user(me["id"])["has_usable_password"] is False
    # El superusuario local sigue entrando con el ModelBackend.
    client.cookies.clear()
    assert login(client, "admin", PWD).status_code == 200


def test_permission_denied_stops_the_chain(tmp_path):
    backends = (BlockedHoursBackend, ModelBackend)
    client, kit = make(tmp_path, authentication_backends=backends)
    kit.create_user("nocturno", PWD)
    res = login(client, "nocturno", PWD)
    assert res.status_code == 403 and res.json()["code"] == "outside_hours"  # ModelBackend no llegó a probarse


def test_broken_backend_does_not_block_the_others(tmp_path):
    client, _ = make(tmp_path, authentication_backends=(BrokenBackend(), ModelBackend()))
    assert login(client, "admin", PWD).status_code == 200


def test_backend_with_other_credentials_is_skipped_for_password_login(tmp_path):
    _client, kit = make(tmp_path, authentication_backends=(PinBackend, ModelBackend))
    assert kit.authenticate("admin", PWD).backend.endswith("ModelBackend")  # PinBackend no acepta username/password
    assert kit.authenticate(pin="4321").username == "admin"


def test_removing_a_backend_invalidates_its_sessions(tmp_path):
    backends = (f"{__name__}.FakeLDAPBackend", "djauth.backends.ModelBackend")
    client, _ = make(tmp_path, authentication_backends=backends)
    login(client, "ana.ldap", "Clave-Del-Directorio-1")
    cookie = client.cookies.get("sessionid")
    client2, _ = make(tmp_path, authentication_backends=("djauth.backends.ModelBackend",))
    client2.cookies.set("sessionid", cookie)
    assert client2.get("/auth/api/me").status_code == 401


def test_allow_all_users_backend_lets_inactive_users_in(tmp_path):
    client, kit = make(tmp_path, authentication_backends=("djauth.backends.AllowAllUsersModelBackend",))
    kit.create_user("inactivo", PWD, is_active=False)
    assert login(client, "inactivo", PWD).status_code == 200
    client2, kit2 = make(tmp_path / "b")
    kit2.create_user("inactivo", PWD, is_active=False)
    assert login(client2, "inactivo", PWD).status_code == 401


def test_invalid_backend_path_fails_fast(tmp_path):
    with pytest.raises(ValueError, match="No se pudo cargar el backend"):
        AuthKit(AuthSettings(database_url="sqlite://", authentication_backends=("no.existe.Backend",)))
    with pytest.raises(ValueError, match="vacío"):
        AuthKit(AuthSettings(database_url="sqlite://", authentication_backends=()))


# ---------------------------------------------------------------------- columnas propias
def test_user_mixin_adds_real_columns(tmp_path):
    client, kit = make(tmp_path, user_mixin=Perfil)
    columns = {c["name"] for c in inspect(kit.engine).get_columns("auth_user")}
    assert {"telefono", "sede", "turno", "es_supervisor", "ingreso"} <= columns
    described = {f["name"]: f for f in client.get("/auth/api/config").json()["user_fields"]}
    assert described["sede"]["type"] == "choice" and described["sede"]["choices"] == ["Norte", "Sur"]
    assert described["telefono"]["label"] == "Teléfono" and described["telefono"]["max_length"] == 20
    assert (described["turno"]["type"], described["es_supervisor"]["type"], described["ingreso"]["type"]) == (
        "integer",
        "bool",
        "date",
    )
    assert described["codigo_sap"]["editable"] is False

    login(client, "admin", PWD)
    body = {"username": "op", "password": PWD, "telefono": "+1 555 0100", "sede": "Sur", "turno": "2", "ingreso": "2026-03-01"}
    created = client.post("/auth/api/users", json=body)
    assert created.status_code == 201, created.text
    user = created.json()
    assert (user["telefono"], user["sede"], user["turno"], user["ingreso"], user["es_supervisor"]) == (
        "+1 555 0100", "Sur", 2, "2026-03-01", False,
    )  # fmt: skip
    updated = client.patch(f"/auth/api/users/{user['id']}", json={"es_supervisor": True, "codigo_sap": "X"}).json()
    assert updated["es_supervisor"] is True and updated["codigo_sap"] is None  # no editable: se ignora
    # Se leen como atributos del usuario autenticado.
    client.cookies.clear()
    login(client, "op", PWD)
    assert kit.authenticate("op", PWD).sede == "Sur"
    log = kit.list_log(object_type="user", object_id=str(user["id"]))[0]
    assert any(e["action"] == "change" and "es_supervisor" in e["message"] for e in log)


def test_user_mixin_validation_errors_are_per_field(tmp_path):
    client, _ = make(tmp_path, user_mixin=Perfil)
    login(client, "admin", PWD)
    res = client.post(
        "/auth/api/users",
        json={
            "username": "x",
            "password": PWD,
            "sede": "Este",
            "turno": "dos",
            "telefono": "1" * 30,
            "ingreso": "ayer",
            "color": "azul",
        },
    )
    assert res.status_code == 400
    errors = res.json()["errors"]
    assert set(errors) == {"color"}  # primero los campos que no existen
    res = client.post(
        "/auth/api/users",
        json={"username": "x", "password": PWD, "sede": "Este", "turno": "dos", "telefono": "1" * 30, "ingreso": "ayer"},
    )
    errors = res.json()["errors"]
    assert "Elija una de" in errors["sede"][0] and "entero" in errors["turno"][0]
    assert "Máximo 20" in errors["telefono"][0] and "fecha" in errors["ingreso"][0]


def test_new_columns_are_added_to_an_existing_database(tmp_path):
    make(tmp_path)  # base creada sin columnas propias
    _, kit = make(tmp_path, user_mixin=Perfil)  # la misma base, ahora con el mixin
    columns = {c["name"] for c in inspect(create_engine(f"sqlite:///{tmp_path / 'auth.sqlite3'}")).get_columns("auth_user")}
    assert {"telefono", "sede", "turno"} <= columns
    admin = kit.get_by_username("admin")
    assert admin.telefono == "" and admin.es_supervisor is False  # valores por defecto aplicados a filas viejas


# ---------------------------------------------------------------------- errores descriptivos
def test_errors_have_code_message_hint(tmp_path):
    client, _ = make(tmp_path)
    bad = login(client, "admin", "mal").json()
    assert bad["code"] == "invalid_credentials" and bad["detail"] == "Usuario o contraseña incorrectos."
    assert "restablecer" in bad["hint"]
    anon = client.get("/yo")  # ruta de la aplicación: también usa el formato descriptivo
    assert anon.status_code == 401 and anon.json()["code"] == "not_authenticated"
    login(client, "admin", PWD)
    missing = client.get("/auth/api/users/999").json()
    assert missing["code"] == "not_found" and "999" in missing["detail"]


def test_missing_permission_error_names_the_permission(tmp_path):
    client, kit = make(tmp_path)
    kit.create_user("sinpermiso", PWD)
    login(client, "sinpermiso", PWD)
    res = client.get("/pedidos").json()
    assert res["code"] == "missing_permission" and "ventas.view_pedido" in res["detail"] and res["hint"]


def test_format_errors_are_translated_to_spanish(tmp_path):
    client, _ = make(tmp_path)
    login(client, "admin", PWD)
    res = client.post("/auth/api/users", json={"username": "ok", "groups": "no-es-lista", "is_active": "quizás"})
    assert res.status_code == 422
    body = res.json()
    assert body["code"] == "invalid_format"
    assert body["errors"]["groups"] == ["Debe ser una lista."]
    assert body["errors"]["is_active"] == ["Debe ser verdadero o falso."]
    empty = client.post("/auth/api/users", json={}).json()
    assert empty["errors"]["username"] == ["Este campo es obligatorio."]


def test_lockout_error_says_how_long(tmp_path):
    client, _ = make(tmp_path)
    for _ in range(5):
        login(client, "admin", "mal")
    res = login(client, "admin", PWD)
    body = res.json()
    assert res.status_code == 429 and body["code"] == "too_many_attempts" and body["retry_after"] > 0
    assert "min" in body["detail"]
