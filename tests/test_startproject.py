"""`djauth startproject`: genera un proyecto nuevo, seguro y sin sobrescribir nada."""

from __future__ import annotations

import os
import stat
import sys

import pytest

from djauth.__main__ import main
from djauth.startproject import MINIMUM, TEMPLATE_DIR, TESTED, StartProjectError, create_project


def test_generates_a_complete_project(tmp_path):
    result = create_project("inventario", tmp_path / "inventario", title="Inventario general", lock=False)
    root = result.path
    expected = [
        "pyproject.toml", "README.md", "Dockerfile", "compose.yaml", ".env", ".env.example", ".gitignore",
        ".dockerignore", "alembic.ini", "migrations/env.py", "migrations/versions/0001_productos.py",
        "src/inventario/main.py", "src/inventario/core/security.py", "src/inventario/api/v1/productos.py",
        "tests/test_app.py", ".github/workflows/ci.yml",
    ]  # fmt: skip
    for relative in expected:
        assert (root / relative).is_file(), relative
    # No quedan marcadores sin reemplazar ni archivos de plantilla.
    for path in root.rglob("*"):
        if path.is_file():
            assert not path.name.endswith(".tpl"), path
            text = path.read_text(encoding="utf-8")
            assert "__paquete__" not in text and "__nombre__" not in text, path
    assert 'description = "Inventario general"' in (root / "pyproject.toml").read_text()
    # Todo el código generado compila.
    for py in root.rglob("*.py"):
        compile(py.read_text(encoding="utf-8"), str(py), "exec")


def test_env_has_unique_secrets_and_private_permissions(tmp_path):
    a = create_project("uno", tmp_path / "uno", lock=False)
    b = create_project("dos", tmp_path / "dos", lock=False)
    env_a = (a.path / ".env").read_text()
    env_b = (b.path / ".env").read_text()
    secret_a = next(line for line in env_a.splitlines() if line.startswith("APP_SECRET_KEY="))
    assert len(secret_a) > 60 and secret_a not in env_b
    assert f"APP_ADMIN_PASSWORD={a.admin_password}" in env_a
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(a.path / ".env").st_mode) == 0o600
    # El ejemplo, que sí va al repositorio, no lleva secretos.
    example = (a.path / ".env.example").read_text()
    assert "APP_SECRET_KEY=\n" in example and a.admin_password not in example
    assert ".env" in (a.path / ".gitignore").read_text().splitlines()


@pytest.mark.parametrize(("db", "driver", "image"), [("postgresql", "psycopg", "postgres:"), ("mysql", "pymysql", "mysql:")])
def test_database_choice(tmp_path, db, driver, image):
    result = create_project("app_" + db[:5], tmp_path / db, db=db, lock=False)
    assert driver in (result.path / "pyproject.toml").read_text()
    assert image in (result.path / "compose.yaml").read_text()
    env = (result.path / ".env").read_text()
    password = next(line.split("=", 1)[1] for line in env.splitlines() if line.startswith("DB_PASSWORD="))
    assert len(password) > 16 and password in env.split("APP_DATABASE_URL=")[1].splitlines()[0]
    assert "CAMBIAR" in (result.path / ".env.example").read_text()


def test_version_modes(tmp_path):
    tested = (create_project("fijo", tmp_path / "fijo", lock=False).path / "pyproject.toml").read_text()
    latest = (create_project("nuevo", tmp_path / "nuevo", versions="ultimas", lock=False).path / "pyproject.toml").read_text()
    assert f'"sqlalchemy=={TESTED["sqlalchemy"]}"' in tested
    assert f'"sqlalchemy>={MINIMUM["sqlalchemy"]}"' in latest
    assert set(TESTED) == set(MINIMUM)


@pytest.mark.parametrize("name", ["Inventario", "1app", "mi-app", "class", "djauth", "fastapi", "a", "x" * 60])
def test_invalid_names_are_rejected(tmp_path, name):
    with pytest.raises(StartProjectError):
        create_project(name, tmp_path / "p", lock=False)


def test_never_overwrites_an_existing_folder(tmp_path):
    target = tmp_path / "existente"
    target.mkdir()
    (target / "importante.txt").write_text("no tocar")
    with pytest.raises(StartProjectError, match="no está vacía"):
        create_project("existente", target, lock=False)
    assert (target / "importante.txt").read_text() == "no tocar"
    assert sorted(p.name for p in target.iterdir()) == ["importante.txt"]


def test_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["startproject", "tienda", "--db", "postgresql", "--sin-lock"]) == 0
    out = capsys.readouterr().out
    assert "Proyecto creado" in out and "uv sync" in out and "contraseña" in out
    assert (tmp_path / "tienda" / "src" / "tienda" / "main.py").exists()
    assert main(["startproject", "tienda", "--sin-lock"]) == 1
    assert "no está vacía" in capsys.readouterr().err


def test_template_is_shipped_with_the_package():
    names = {p.relative_to(TEMPLATE_DIR).as_posix() for p in TEMPLATE_DIR.rglob("*.tpl")}
    assert {".env.example.tpl", ".gitignore.tpl", ".dockerignore.tpl", ".github/workflows/ci.yml.tpl"} <= names
