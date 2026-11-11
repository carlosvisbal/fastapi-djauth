from fastapi.testclient import TestClient

PRODUCTO = {"codigo": "PRD-001", "nombre": "Producto de ejemplo", "precio": "125000.50", "stock": 10}


def test_health_is_public(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_everything_else_requires_login(client: TestClient) -> None:
    res = client.get("/api/v1/productos")
    assert res.status_code == 401
    assert res.json()["code"] == "not_authenticated"


def test_crud(admin: TestClient) -> None:
    creado = admin.post("/api/v1/productos", json=PRODUCTO)
    assert creado.status_code == 201, creado.text
    pid = creado.json()["id"]
    assert admin.post("/api/v1/productos", json=PRODUCTO).status_code == 409  # código repetido
    assert admin.patch(f"/api/v1/productos/{pid}", json={"stock": 7}).json()["stock"] == 7
    pagina = admin.get("/api/v1/productos", params={"q": "ejemplo"}).json()
    assert pagina["total"] == 1
    assert admin.delete(f"/api/v1/productos/{pid}").status_code == 204
    assert admin.get(f"/api/v1/productos/{pid}").status_code == 404


def test_reader_role_can_only_read(admin: TestClient) -> None:
    lector = next(g for g in admin.get("/auth/api/groups").json()["items"] if g["name"] == "Lector")
    datos = {"username": "lector", "password": "Clave-Lector-2026", "groups": [lector["id"]]}
    assert admin.post("/auth/api/users", json=datos).status_code == 201
    token = admin.post("/auth/api/token", json={"username": "lector", "password": "Clave-Lector-2026"}).json()
    headers = {"Authorization": f"Bearer {token['access_token']}"}
    assert admin.get("/api/v1/productos", headers=headers).status_code == 200
    res = admin.post("/api/v1/productos", json=PRODUCTO, headers=headers)
    assert res.status_code == 403
    assert "inventario.add_producto" in res.json()["detail"]


def test_invalid_data_is_rejected(admin: TestClient) -> None:
    res = admin.post("/api/v1/productos", json={**PRODUCTO, "precio": "-1"})
    assert res.status_code == 422
