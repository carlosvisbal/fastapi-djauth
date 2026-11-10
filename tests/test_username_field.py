"""USERNAME_FIELD de Django: se inicia sesión con el usuario o con el correo, no con los dos."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from djauth import AuthKit, AuthSettings

PWD = "Clave-Segura-2026"


def make(tmp_path, **overrides):
    kit = AuthKit(
        AuthSettings(
            database_url=f"sqlite:///{tmp_path / 'auth.sqlite3'}",
            password_iterations=1000,
            bootstrap_superuser=("admin", PWD, "admin@example.com"),
            **overrides,
        )
    ).init()
    app = FastAPI()
    kit.install(app)
    return TestClient(app), kit


def test_default_logs_in_with_username_only(tmp_path):
    client, _ = make(tmp_path)
    assert client.post("/auth/api/login", json={"username": "admin", "password": PWD}).status_code == 200
    client.cookies.clear()
    # El correo no sirve para entrar cuando el campo es "username".
    assert client.post("/auth/api/login", json={"username": "admin@example.com", "password": PWD}).status_code == 401
    assert client.get("/auth/api/config").json()["username_field"] == "username"


def test_email_mode_logs_in_with_email_only(tmp_path):
    client, kit = make(tmp_path, username_field="email")
    admin = kit.get_by_username("admin@example.com")
    assert admin is not None and admin.email == "admin@example.com"  # el superusuario inicial usa el correo
    assert client.post("/auth/api/login", json={"username": "ADMIN@Example.com", "password": PWD}).status_code == 200
    client.cookies.clear()
    assert client.post("/auth/api/login", json={"email": "admin@example.com", "password": PWD}).status_code == 200
    client.cookies.clear()
    assert client.post("/auth/api/login", json={"username": "admin", "password": PWD}).status_code == 401
    token = client.post("/auth/api/token", data={"username": "admin@example.com", "password": PWD})
    assert token.status_code == 200
    assert client.get("/auth/api/config").json()["username_field"] == "email"


def test_email_mode_requires_unique_email(tmp_path):
    client, kit = make(tmp_path, username_field="email")
    client.post("/auth/api/login", json={"username": "admin@example.com", "password": PWD})
    created = client.post("/auth/api/users", json={"email": "Ana@Empresa.COM", "password": PWD})
    assert created.status_code == 201
    user = created.json()
    assert user["email"] == "Ana@empresa.com" and user["username"] == "Ana@empresa.com"
    dup = client.post("/auth/api/users", json={"email": "ana@EMPRESA.com", "password": PWD})
    assert dup.status_code == 400 and dup.json()["code"] == "email_taken"
    missing = client.post("/auth/api/users", json={"username": "ana2", "password": PWD})
    assert missing.status_code == 400 and "email" in missing.json()["errors"]
    # Cambiar el correo cambia también con qué se entra.
    client.patch(f"/auth/api/users/{user['id']}", json={"email": "ana.perez@empresa.com", "username": "ignorado"})
    assert kit.authenticate("ana.perez@empresa.com", PWD).username == "ana.perez@empresa.com"
    taken = client.patch(f"/auth/api/users/{user['id']}", json={"email": "admin@example.com"})
    assert taken.status_code == 400 and taken.json()["code"] == "email_taken"


def test_database_enforces_unique_email_index(tmp_path):
    _, kit = make(tmp_path, username_field="email")
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    with kit.engine.connect() as conn:
        names = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'index'"))}
    assert "auth_user_email_lower_uniq" in names
    # Aunque alguien se salte la aplicación, la base rechaza el correo repetido.
    with pytest.raises(IntegrityError), kit.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO auth_user (username, password, email, first_name, last_name, is_active, is_staff, "
                "is_superuser, date_joined, extra) VALUES ('otro', '!', 'ADMIN@example.com', '', '', 1, 0, 0, '2026-01-01', '{}')"
            )
        )


def test_invalid_username_field_is_rejected():
    with pytest.raises(ValueError, match='"username" o "email"'):
        AuthKit(AuthSettings(database_url="sqlite://", username_field="telefono"))
