from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from __paquete__.core.config import Settings
from __paquete__.db import Base
from __paquete__.main import create_app

ADMIN_PASSWORD = "Clave-De-Prueba-2026"


@pytest.fixture
def settings(tmp_path) -> Settings:  # type: ignore[no-untyped-def]
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.sqlite3'}",
        secret_key=SecretStr("clave-de-pruebas"),
        admin_password=SecretStr(ADMIN_PASSWORD),
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)  # en producción las tablas las crea Alembic
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin(client: TestClient) -> TestClient:
    res = client.post("/auth/api/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    assert res.status_code == 200, res.text
    return client
