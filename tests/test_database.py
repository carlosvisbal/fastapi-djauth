"""Configuración de la base con el formato DATABASES de Django."""

from __future__ import annotations

import pytest

from djauth import AuthKit, AuthSettings, DatabaseConfigError, url_from_django


def test_postgresql_engine_and_special_characters_in_password():
    url = url_from_django(
        {
            "ENGINE": "django.db.backends.postgresql_psycopg2",
            "NAME": "miapp",
            "USER": "app",
            "PASSWORD": "p@ss/w#rd:1",
            "HOST": "db.local",
            "PORT": "5432",
            "OPTIONS": {"sslmode": "require"},
            "DRIVER": "psycopg2",
        }
    )
    assert url.drivername == "postgresql+psycopg2"
    assert (url.username, url.password, url.host, url.port, url.database) == ("app", "p@ss/w#rd:1", "db.local", 5432, "miapp")
    assert url.query == {"sslmode": "require"}
    # La contraseña queda escapada en la URL: los caracteres especiales no rompen la conexión.
    assert "p%40ss%2Fw%23rd%3A1" in url.render_as_string(hide_password=False)


def test_driver_is_chosen_from_installed_packages(monkeypatch):
    import djauth.database as database

    monkeypatch.setattr(database.importlib.util, "find_spec", lambda name: object() if name == "psycopg2" else None)
    assert url_from_django({"ENGINE": "django.db.backends.postgresql", "NAME": "x"}).drivername == "postgresql+psycopg2"
    monkeypatch.setattr(database.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(DatabaseConfigError) as info:
        url_from_django({"ENGINE": "django.db.backends.mysql", "NAME": "x"})
    assert "fastapi-djauth[mysql]" in info.value.hint


def test_sqlite_engine(tmp_path):
    path = tmp_path / "sub" / "auth.sqlite3"
    kit = AuthKit(
        AuthSettings(database={"ENGINE": "django.db.backends.sqlite3", "NAME": str(path)}, password_iterations=1000)
    ).init()
    kit.create_user("ana", "Clave-Segura-2026")
    assert path.exists() and kit.authenticate("ana", "Clave-Segura-2026").username == "ana"
    memory = url_from_django({"ENGINE": "sqlite3", "NAME": ":memory:"})
    assert memory.drivername == "sqlite" and memory.database is None


def test_database_takes_priority_over_database_url(tmp_path):
    path = tmp_path / "elegida.sqlite3"
    AuthKit(AuthSettings(database_url="sqlite:///no-usar.sqlite3", database={"ENGINE": "sqlite3", "NAME": str(path)})).init()
    assert path.exists()


@pytest.mark.parametrize(
    ("config", "fragment"),
    [
        ({}, "Falta ENGINE"),
        ({"ENGINE": "django.db.backends.mongodb", "NAME": "x"}, "no soportado"),
        ({"ENGINE": "postgresql", "DRIVER": "psycopg"}, "Falta NAME"),
        ({"ENGINE": "postgresql", "NAME": "x", "PORT": "cinco", "DRIVER": "psycopg"}, "PORT debe ser un número"),
    ],
)
def test_descriptive_configuration_errors(config, fragment):
    with pytest.raises(DatabaseConfigError) as info:
        url_from_django(config)
    assert fragment in info.value.message and info.value.code == "database_config"


def test_async_driver_is_rejected_with_a_clear_message():
    with pytest.raises(DatabaseConfigError, match="asíncrono") as exc:
        AuthKit(AuthSettings(database_url="postgresql+asyncpg://u:p@localhost/db"))
    assert "postgresql+psycopg" in exc.value.hint
    with pytest.raises(DatabaseConfigError, match="asíncrono"):
        AuthKit(AuthSettings(database={"ENGINE": "postgresql", "NAME": "db", "DRIVER": "asyncpg"}))


def test_oracle_name_is_the_service_name_and_sid_is_optional():
    base = {
        "ENGINE": "oracle",
        "NAME": "FREEPDB1",
        "USER": "app",
        "PASSWORD": "x",
        "HOST": "db",
        "PORT": 1521,
        "DRIVER": "oracledb",
    }
    url = url_from_django(base)
    assert url.database is None and url.query == {"service_name": "FREEPDB1"}
    legacy = url_from_django({**{k: v for k, v in base.items() if k != "NAME"}, "OPTIONS": {"sid": "ORCL"}})
    assert legacy.database == "ORCL" and "service_name" not in legacy.query
