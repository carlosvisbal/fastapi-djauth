"""djauth: usuarios, grupos, permisos, sesión y Bearer, seguridad y administración."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from djauth import AuthKit, AuthSettings, AuthUser, ExtraField, current_user, require_perm, rule, ws_user
from djauth.hashers import check_password, make_password, must_update

PWD = "Clave-Segura-2026"


def make_app(tmp_path, *, protect: bool = False, **overrides) -> tuple[FastAPI, AuthKit]:
    settings = AuthSettings(
        database_url=f"sqlite:///{tmp_path / 'auth.sqlite3'}",
        password_iterations=1000,  # rápido en pruebas; en producción, el valor de Django (1,2 M)
        bootstrap_superuser=("admin", PWD, "admin@example.com"),
        permissions={"ventas": {"view_pedido": "Puede ver pedidos", "aprobar_pedido": "Puede aprobar pedidos"}},
        **overrides,
    )
    kit = AuthKit(settings).init()
    app = FastAPI()

    @app.get("/pedidos")
    def pedidos(user: AuthUser = Depends(require_perm("ventas.view_pedido"))):
        return {"user": user.username}

    @app.get("/privado")
    def privado(user: AuthUser = Depends(current_user)):
        return {"user": user.username}

    @app.post("/accion")
    def accion(user: AuthUser = Depends(current_user)):
        return {"ok": True}

    @app.get("/publico")
    def publico():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        user = ws_user(websocket)
        await websocket.accept()
        await websocket.send_json({"user": user.username if user else None})
        await websocket.close()

    kit.install(
        app,
        protect=protect,
        exempt={"/health"},
        rules=[rule(r"^/accion$", "ventas.aprobar_pedido", methods=["POST"])],
        api_key="llave-de-servicio",
    )
    return app, kit


@pytest.fixture
def setup(tmp_path):
    app, kit = make_app(tmp_path)
    with TestClient(app) as client:
        yield client, kit


def login(client, username="admin", password=PWD):
    res = client.post("/auth/api/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return res


def bearer(client, username="admin", password=PWD) -> dict:
    res = client.post("/auth/api/token", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


# ---------------------------------------------------------------------- contraseñas
def test_password_hash_is_django_compatible():
    encoded = make_password("secreto", iterations=1000, salt="seasalt")
    assert encoded.startswith("pbkdf2_sha256$1000$seasalt$")
    assert check_password("secreto", encoded) and not check_password("otro", encoded)
    # Generado con Django 6.0.10: make_password("contraseña-ñ", salt="seasalt2026") (1 200 000 iteraciones).
    django_hash = "pbkdf2_sha256$1200000$seasalt2026$AaYsk6cgZiXXOY8jNXKwbfZuXq5WAlYEWJOlVM2qS20="
    assert check_password("contraseña-ñ", django_hash) and not check_password("contraseña", django_hash)
    assert make_password("contraseña-ñ", 1_200_000, "seasalt2026") == django_hash
    assert must_update(encoded, 1_200_000)
    assert not check_password("x", make_password(None))


def test_password_validators(setup):
    _client, kit = setup
    for bad, reason in (("corta", "corta"), ("12345678901", "números"), ("password123", "común"), ("operario-juan", "parece")):
        with pytest.raises(Exception) as info:
            kit.create_user("operario-juan", bad)
        assert reason in str(info.value.errors).lower(), (bad, info.value.errors)


# ---------------------------------------------------------------------- sesión
def test_session_login_me_logout(setup):
    client, _kit = setup
    assert client.get("/auth/api/me").status_code == 401
    res = login(client)
    cookie = res.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie.replace("Lax", "lax")
    me = client.get("/auth/api/me").json()
    assert me["username"] == "admin" and me["is_superuser"] and "ventas.aprobar_pedido" not in me["permissions"]
    assert client.get("/pedidos").json() == {"user": "admin"}  # superusuario: todos los permisos
    client.post("/auth/api/logout")
    assert client.get("/auth/api/me").status_code == 401


def test_session_token_is_stored_hashed(setup):
    client, kit = setup
    login(client)
    token = client.cookies.get("sessionid")
    with kit._db() as db:
        stored = [s.key_hash for s in db.query(kit.models.Session)]
    assert token not in stored and len(stored[0]) == 64


def test_wrong_password_and_lockout(setup):
    client, _kit = setup
    for _ in range(5):
        res = client.post("/auth/api/login", json={"username": "admin", "password": "mal"})
        assert res.status_code == 401
    res = client.post("/auth/api/login", json={"username": "admin", "password": PWD})
    assert res.status_code == 429 and int(res.headers["retry-after"]) > 0
    # Un usuario inexistente da el mismo mensaje que una contraseña errónea.
    other = client.post("/auth/api/login", json={"username": "noexiste", "password": "x"}).json()
    assert other["detail"] == "Usuario o contraseña incorrectos."


def test_csrf_blocks_cross_site_requests_with_cookie(setup):
    client, _kit = setup
    login(client)
    assert client.post("/accion", headers={"Origin": "http://testserver"}).status_code == 200
    evil = client.post("/accion", headers={"Origin": "https://malicioso.example"})
    assert evil.status_code == 403 and "CSRF" in evil.json()["detail"]
    assert client.post("/auth/api/users", json={"username": "x"}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


# ---------------------------------------------------------------------- Bearer
def test_bearer_token_flow(setup):
    client, _kit = setup
    headers = bearer(client)
    assert client.get("/auth/api/me", headers=headers).json()["username"] == "admin"
    # Un token Bearer no sirve como cookie, ni la cookie como Bearer.
    token = headers["Authorization"].split()[1]
    client.cookies.set("sessionid", token)
    assert client.get("/auth/api/me").status_code == 401
    client.cookies.clear()
    # Sin cookie no hay CSRF que comprobar: un cliente de API puede escribir desde cualquier origen.
    assert client.post("/accion", headers={**headers, "Origin": "https://otra-app.example"}).status_code == 200
    client.post("/auth/api/logout", headers=headers)
    assert client.get("/auth/api/me", headers=headers).status_code == 401  # revocado al instante


def test_token_endpoint_accepts_oauth2_form(setup):
    client, _ = setup
    res = client.post("/auth/api/token", data={"username": "admin", "password": PWD, "grant_type": "password"})
    assert res.status_code == 200 and res.json()["token_type"] == "bearer"


def test_invalid_bearer_does_not_fall_back_to_cookie(setup):
    client, _ = setup
    login(client)
    assert client.get("/auth/api/me", headers={"Authorization": "Bearer falso"}).status_code == 401


def test_auth_modes_can_be_switched(tmp_path):
    app, _ = make_app(tmp_path / "a", enable_sessions=False)
    with TestClient(app) as client:
        assert client.post("/auth/api/login", json={"username": "admin", "password": PWD}).status_code == 403
        assert client.get("/auth/api/config").json()["sessions"] is False
        assert client.get("/auth/api/me", headers=bearer(client)).status_code == 200
    app, _ = make_app(tmp_path / "b", enable_bearer=False)
    with TestClient(app) as client:
        assert client.post("/auth/api/token", json={"username": "admin", "password": PWD}).status_code == 403
        login(client)


def test_password_change_revokes_other_sessions_and_tokens(setup):
    client, _kit = setup
    other = bearer(client)
    login(client)
    res = client.post("/auth/api/me/password", json={"old_password": PWD, "new_password": "Nueva-Clave-Sede-9"})
    assert res.status_code == 200
    assert client.get("/auth/api/me").status_code == 200  # la sesión actual sigue
    assert client.get("/auth/api/me", headers=other).status_code == 401  # las demás se cerraron
    wrong = client.post("/auth/api/me/password", json={"old_password": "mal", "new_password": "Otra-Clave-Sede-9"})
    assert wrong.status_code == 400 and "old_password" in wrong.json()["errors"]


# ---------------------------------------------------------------------- permisos y roles
def test_groups_grant_permissions(setup):
    client, kit = setup
    perms = {p["key"]: p["id"] for p in kit.list_permissions()}
    group = kit.create_group("Vendedores", [perms["ventas.view_pedido"]])
    kit.create_user("ana", PWD, groups=[group["id"]])
    kit.create_user("luis", PWD)
    login(client, "ana", PWD)
    assert client.get("/pedidos").json() == {"user": "ana"}
    client.post("/auth/api/logout")
    login(client, "luis", PWD)
    res = client.get("/pedidos")
    assert res.status_code == 403 and "ventas.view_pedido" in res.json()["detail"]
    # Al darle el permiso directo, entra sin cerrar sesión.
    kit.update_user(kit.get_by_username("luis").id, {"permissions": [perms["ventas.view_pedido"]]})
    assert client.get("/pedidos").status_code == 200


def test_ensure_group_creates_role_once(setup):
    _, kit = setup
    assert kit.ensure_group("Supervisor", ["ventas.view_pedido", "ventas.aprobar_pedido"]) is True
    assert kit.ensure_group("Supervisor", ["ventas.view_pedido"]) is False  # no pisa lo ajustado
    assert len(next(g for g in kit.list_groups() if g["name"] == "Supervisor")["permissions"]) == 2


def test_inactive_user_loses_access_immediately(setup):
    client, kit = setup
    kit.create_user("pepe", PWD)
    headers = bearer(client, "pepe", PWD)
    kit.update_user(kit.get_by_username("pepe").id, {"is_active": False})
    assert client.get("/auth/api/me", headers=headers).status_code == 401
    assert client.post("/auth/api/token", json={"username": "pepe", "password": PWD}).status_code == 401


# ---------------------------------------------------------------------- administración
def test_admin_crud_requires_staff_and_permissions(setup):
    client, kit = setup
    perms = {p["key"]: p["id"] for p in kit.list_permissions()}
    kit.create_user("rrhh", PWD, is_staff=True, permissions=[perms["auth.view_user"], perms["auth.add_user"]])
    kit.create_user("normal", PWD)
    login(client, "normal", PWD)
    assert client.get("/auth/api/users").status_code == 403
    client.post("/auth/api/logout")
    login(client, "rrhh", PWD)
    assert client.get("/auth/api/users").json()["total"] == 3
    created = client.post("/auth/api/users", json={"username": "nuevo", "password": PWD, "email": "N@EXAMPLE.COM"})
    assert created.status_code == 201 and created.json()["email"] == "N@example.com"
    assert client.patch(f"/auth/api/users/{created.json()['id']}", json={"first_name": "X"}).status_code == 403
    dup = client.post("/auth/api/users", json={"username": "NUEVO", "password": PWD})
    assert dup.status_code == 400 and "username" in dup.json()["errors"]


def test_staff_cannot_escalate_privileges(setup):
    client, kit = setup
    perms = {p["key"]: p["id"] for p in kit.list_permissions()}
    admin_perms = [
        perms[k] for k in ("auth.view_user", "auth.add_user", "auth.change_user", "auth.view_group", "auth.change_group")
    ]
    kit.create_user("jefe", PWD, is_staff=True, permissions=admin_perms)
    login(client, "jefe", PWD)
    me = client.get("/auth/api/me").json()
    assert client.post("/auth/api/users", json={"username": "x1", "password": PWD, "is_superuser": True}).status_code == 403
    assert client.patch(f"/auth/api/users/{me['id']}", json={"is_superuser": True}).status_code == 403
    # No puede darse ni dar permisos que no tiene.
    assert (
        client.patch(
            f"/auth/api/users/{me['id']}", json={"permissions": [*admin_perms, perms["ventas.aprobar_pedido"]]}
        ).status_code
        == 403
    )
    admin_id = kit.get_by_username("admin").id
    assert client.post(f"/auth/api/users/{admin_id}/password", json={"password": "Hackeo-Total-2026"}).status_code == 403
    assert client.post(f"/auth/api/users/{admin_id}/reset-link").status_code == 403


def test_last_superuser_is_protected(setup):
    client, kit = setup
    admin_id = kit.get_by_username("admin").id
    login(client)
    assert client.patch(f"/auth/api/users/{admin_id}", json={"is_active": False}).status_code == 400
    assert client.delete(f"/auth/api/users/{admin_id}").status_code == 400
    kit.create_superuser("otro", PWD)
    assert client.patch(f"/auth/api/users/{admin_id}", json={"is_superuser": False}).status_code == 200


def test_reset_link_is_single_use(setup):
    client, kit = setup
    kit.create_user("olvido", None)  # sin contraseña: no puede entrar
    uid = kit.get_by_username("olvido").id
    assert client.post("/auth/api/login", json={"username": "olvido", "password": ""}).status_code == 422
    login(client)
    link = client.post(f"/auth/api/users/{uid}/reset-link").json()
    assert "#uid=" in link["url"]  # token en el fragmento: no llega a los logs del servidor
    client.post("/auth/api/logout")
    body = {"uid": uid, "token": link["token"], "new_password": "Mi-Clave-Nueva-77"}
    assert client.post("/auth/api/reset/confirm", json=body).status_code == 200
    login(client, "olvido", "Mi-Clave-Nueva-77")
    assert client.post("/auth/api/reset/confirm", json={**body, "new_password": "Otra-Clave-Nueva-88"}).status_code == 400
    assert client.post("/auth/api/reset/confirm", json={**body, "token": "1-abc"}).status_code == 400


def test_extra_fields(tmp_path):
    fields = (
        ExtraField("sede", "Sede", "choice", ("Norte", "Sur"), required=True),
        ExtraField("turno", "Turno", "number"),
    )
    app, _kit = make_app(tmp_path, extra_fields=fields)
    with TestClient(app) as client:
        login(client)
        assert client.get("/auth/api/config").json()["extra_fields"][0]["choices"] == ["Norte", "Sur"]
        missing = client.post("/auth/api/users", json={"username": "op", "password": PWD})
        assert missing.status_code == 400 and "extra.sede" in missing.json()["errors"]
        ok = client.post(
            "/auth/api/users", json={"username": "op", "password": PWD, "extra": {"sede": "Sur", "turno": "2"}}
        )
        assert ok.json()["extra"] == {"sede": "Sur", "turno": 2}
        assert (
            client.post("/auth/api/users", json={"username": "op2", "password": PWD, "extra": {"sede": "Este"}}).status_code
            == 400
        )


def test_audit_log(setup):
    client, _kit = setup
    login(client)
    created = client.post("/auth/api/users", json={"username": "auditado", "password": PWD}).json()
    client.patch(f"/auth/api/users/{created['id']}", json={"email": "a@b.co"})
    log = client.get(f"/auth/api/log?object_type=user&object_id={created['id']}").json()["items"]
    assert [e["action"] for e in log] == ["change", "add"]
    assert log[0]["username"] == "admin" and "email" in log[0]["message"]


# ---------------------------------------------------------------------- protección global
def test_protect_mode_guards_whole_app(tmp_path):
    app, kit = make_app(tmp_path, protect=True)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200  # exenta
        assert client.get("/publico").status_code == 401
        page = client.get("/publico", headers={"Accept": "text/html"}, follow_redirects=False)
        assert page.status_code == 303 and page.headers["location"] == "/auth/login?next=%2Fpublico"
        assert client.get("/auth/login").status_code == 200  # la página de acceso es pública
        assert client.get("/auth/static/djauth.css").status_code == 200
        assert client.get("/publico", headers={"X-API-Key": "llave-de-servicio"}).status_code == 200
        kit.create_user("op", PWD)
        login(client, "op", PWD)
        assert client.get("/publico").status_code == 200
        # La regla exige un permiso para POST /accion.
        assert client.post("/accion", headers={"Origin": "http://testserver"}).status_code == 403


def test_websocket_auth(tmp_path):
    app, _kit = make_app(tmp_path, protect=True)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws"):
            pass
        token = bearer(client)["Authorization"].split()[1]
        with client.websocket_connect(f"/ws?access_token={token}") as ws:
            assert ws.receive_json() == {"user": "admin"}
        login(client)
        with client.websocket_connect("/ws", headers={"Origin": "http://testserver"}) as ws:
            assert ws.receive_json() == {"user": "admin"}


def test_pages_have_security_headers(setup):
    client, _ = setup
    for page in ("login", "admin", "account", "reset"):
        res = client.get(f"/auth/{page}")
        assert res.status_code == 200
        assert "frame-ancestors 'none'" in res.headers["content-security-policy"]
        assert res.headers["x-frame-options"] == "DENY" and res.headers["cache-control"] == "no-store"


def test_cli(tmp_path, monkeypatch, capsys):
    from djauth.__main__ import main

    db = f"sqlite:///{tmp_path / 'cli.sqlite3'}"
    monkeypatch.setenv("DJAUTH_PASSWORD", PWD)
    assert main(["--db", db, "createsuperuser", "--username", "root", "--email", "r@x.co"]) == 0
    assert main(["--db", db, "listusers"]) == 0
    assert "root" in capsys.readouterr().out
    monkeypatch.setenv("DJAUTH_PASSWORD", "corta")
    assert main(["--db", db, "changepassword", "root"]) == 1


# ---------------------------------------------------------------------- revisión de seguridad
def test_cross_site_websocket_hijacking_is_blocked(tmp_path):
    app, _ = make_app(tmp_path, protect=True)
    with TestClient(app) as client:
        login(client)
        # Otro sitio abre el WebSocket: el navegador envía la cookie, pero el origen no coincide.
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws", headers={"Origin": "https://malicioso.example"}):
            pass
        # Sin Origin (no es un navegador) tampoco se acepta la cookie en un WebSocket.
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws"):
            pass
    app, _ = make_app(tmp_path / "b", protect=False)  # sin middleware: lo comprueba ws_user()
    with TestClient(app) as client:
        login(client)
        with client.websocket_connect("/ws", headers={"Origin": "https://malicioso.example"}) as ws:
            assert ws.receive_json() == {"user": None}


def test_staff_cannot_take_over_users_with_more_permissions(setup):
    client, kit = setup
    perms = {p["key"]: p["id"] for p in kit.list_permissions()}
    kit.create_user("rrhh", PWD, is_staff=True, permissions=[perms["auth.view_user"], perms["auth.change_user"]])
    kit.create_user("gerente", PWD, is_staff=True, permissions=[perms["auth.view_user"], perms["ventas.aprobar_pedido"]])
    kit.create_user("operario", PWD)
    gerente, operario = kit.get_by_username("gerente").id, kit.get_by_username("operario").id
    login(client, "rrhh", PWD)
    for attempt in (
        client.post(f"/auth/api/users/{gerente}/password", json={"password": "Toma-De-Cuenta-2026"}),
        client.post(f"/auth/api/users/{gerente}/reset-link"),
        client.patch(f"/auth/api/users/{gerente}", json={"email": "atacante@example.com"}),
    ):
        assert attempt.status_code == 403 and attempt.json()["code"] == "target_has_more_permissions"
    # Sobre alguien sin permisos adicionales sí puede.
    assert client.post(f"/auth/api/users/{operario}/password", json={"password": "Nueva-Clave-Op-2026"}).status_code == 200


def test_login_from_another_site_is_rejected_even_without_cookie(setup):
    client, _ = setup
    res = client.post(
        "/auth/api/login", json={"username": "admin", "password": PWD}, headers={"Origin": "https://malicioso.example"}
    )
    assert res.status_code == 403 and res.json()["code"] == "csrf_failed"
    ok = client.post("/auth/api/login", json={"username": "admin", "password": PWD}, headers={"Origin": "http://testserver"})
    assert ok.status_code == 200


def test_session_cookie_is_secure_over_https(tmp_path):
    app, _ = make_app(tmp_path)
    with TestClient(app, base_url="https://testserver") as client:
        res = client.post("/auth/api/login", json={"username": "admin", "password": PWD})
        assert "Secure" in res.headers["set-cookie"]
    with TestClient(app) as client:
        res = client.post("/auth/api/login", json={"username": "admin", "password": PWD})
        assert "Secure" not in res.headers["set-cookie"]


def test_samesite_setting_is_validated(tmp_path):
    with pytest.raises(ValueError, match="lax"):
        AuthKit(AuthSettings(database_url="sqlite://", session_cookie_samesite="Lax "))
    with pytest.raises(ValueError, match="session_cookie_secure"):
        AuthKit(AuthSettings(database_url="sqlite://", session_cookie_samesite="none"))
    AuthKit(AuthSettings(database_url="sqlite://", session_cookie_samesite="none", session_cookie_secure=True))
