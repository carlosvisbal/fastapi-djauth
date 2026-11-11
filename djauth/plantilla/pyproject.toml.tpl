[project]
name = "__paquete__"
version = "0.1.0"
description = "__nombre__"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
__dependencias__
]

[dependency-groups]
dev = [
__dependencias_dev__
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/__paquete__"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
line-length = 120
target-version = "py311"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM", "C4", "S", "RUF"]
ignore = ["B008", "RUF001", "RUF002", "RUF003"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "S105", "S106"]
"migrations/**" = ["E501"]

[tool.mypy]
python_version = "3.11"
packages = ["__paquete__"]
mypy_path = "src"
strict = true
plugins = ["pydantic.mypy"]
ignore_missing_imports = true
