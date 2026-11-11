"""Pruebas contra motores reales (PostgreSQL, MySQL…). Se saltan si no hay bases configuradas.

    DJAUTH_TEST_DATABASE_URLS="postgresql+psycopg://u:p@localhost/djauth mysql+pymysql://u:p@localhost/djauth" pytest

Cada prueba usa un prefijo de tabla propio y lo borra al terminar.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import String, create_engine, inspect
from sqlalchemy.orm import Mapped, mapped_column

from djauth import AuthKit, AuthSettings

URLS = os.environ.get("DJAUTH_TEST_DATABASE_URLS", "").split()
PWD = "Clave-Segura-2026"

pytestmark = pytest.mark.skipif(not URLS, reason="DJAUTH_TEST_DATABASE_URLS no está definida")


class Perfil:
    telefono: Mapped[str] = mapped_column(String(20), default="", info={"label": "Teléfono"})


def kit_for(url: str, prefix: str, **overrides) -> AuthKit:
    return AuthKit(AuthSettings(database_url=url, table_prefix=prefix, password_iterations=1000, **overrides)).init()


@pytest.fixture(params=URLS or ["sin-base"], ids=lambda u: u.split(":", 1)[0])
def url_prefix(request):
    url, prefix = request.param, f"t{uuid.uuid4().hex[:8]}_"
    yield url, prefix
    engine = create_engine(url)
    with engine.begin() as conn:
        kit = AuthKit(AuthSettings(database_url=url, table_prefix=prefix, user_mixin=Perfil))
        kit.models.Base.metadata.drop_all(conn)
    engine.dispose()


def test_full_flow(url_prefix):
    url, prefix = url_prefix
    kit = kit_for(url, prefix, username_field="email")
    admin = kit.create_superuser("Admin@Empresa.com", PWD)
    group = kit.create_group("Operador", [p["id"] for p in kit.list_permissions() if p["key"] == "auth.view_user"])
    user = kit.create_user("ana@empresa.com", PWD + "x", groups=[group["id"]], reason="Alta")
    assert kit.authenticate(username="ANA@empresa.com", password=PWD + "x").has_perm("auth.view_user")
    kit.update_user(user["id"], {"first_name": "Ana"}, reason="Corrección")
    items, total = kit.user_history(user["id"], field="first_name")
    assert total == 1 and items[0]["changes"] == {"first_name": {"old": "", "new": "Ana"}}
    token = kit.login(kit.get_by_username(admin["username"]), kind="bearer")
    assert kit.user_from_token(token, "bearer").is_superuser
    # El correo es único sin distinguir mayúsculas.
    with pytest.raises(Exception, match="correo"):
        kit.create_user("ANA@EMPRESA.COM", PWD + "y")


def test_new_custom_column_is_added_to_existing_table(url_prefix):
    url, prefix = url_prefix
    kit_for(url, prefix).create_user("beto", PWD)
    kit = kit_for(url, prefix, user_mixin=Perfil)  # columna nueva en una tabla con datos
    columns = {c["name"] for c in inspect(kit.engine).get_columns(f"{prefix}user")}
    assert "telefono" in columns
    beto = kit.find_user_row("beto")
    assert beto.telefono == ""
    kit.update_user(beto.id, {"telefono": "3001234567"})
    assert kit.get_user(beto.id)["telefono"] == "3001234567"
