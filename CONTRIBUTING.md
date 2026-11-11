# Contribuir a fastapi-djauth

Gracias por querer mejorar el paquete. Esta guía explica cómo preparar el entorno, qué se comprueba en cada cambio y cómo se publica una versión.

## Preparar el entorno

Requiere Python 3.11 o superior. Con [uv](https://docs.astral.sh/uv/) (recomendado):

```bash
git clone https://github.com/carlosvisbal/fastapi-djauth.git && cd fastapi-djauth
uv venv && uv pip install -e ".[test]"
```

O con `pip`: `python -m venv .venv && . .venv/bin/activate && pip install -e ".[test]"`.

## Comprobaciones

Son las mismas que ejecuta la CI en cada pull request:

```bash
pytest                                        # pruebas
uvx ruff check djauth tests examples          # errores y estilo
uvx ruff format --check djauth tests examples # formato
uvx mypy                                      # tipos
uvx bandit -q -r djauth                       # análisis de seguridad del código
```

### Contra PostgreSQL y MySQL reales

Las pruebas usan SQLite. `tests/test_engines.py` repite el flujo principal contra motores reales cuando se le indican:

```bash
docker run -d --name pg -e POSTGRES_USER=djauth -e POSTGRES_PASSWORD=djauth -e POSTGRES_DB=djauth -p 5432:5432 postgres:17-alpine
docker run -d --name my -e MYSQL_ROOT_PASSWORD=root -e MYSQL_USER=djauth -e MYSQL_PASSWORD=djauth -e MYSQL_DATABASE=djauth -p 3306:3306 mysql:8.4
uv pip install -e ".[test,postgres,mysql]"

DJAUTH_TEST_DATABASE_URLS="postgresql+psycopg://djauth:djauth@127.0.0.1:5432/djauth mysql+pymysql://djauth:djauth@127.0.0.1:3306/djauth" \
  pytest tests/test_engines.py -v
```

## Qué se espera de un cambio

- **Pruebas:** toda función nueva o error corregido lleva su prueba.
- **Documentación:** si cambia algo visible, actualice `docs/`, el README y `CHANGELOG.md` (sección "Sin publicar").
- **Idioma:** la documentación, los mensajes y los comentarios están en español.
- **Seguridad:** no se aceptan cambios que debiliten las protecciones por defecto (contraseñas, sesiones, CSRF, escalada de privilegios). Si su cambio toca autenticación, sesiones, permisos o datos personales, explique en el pull request su impacto en la seguridad.
- **Compatibilidad:** se sigue [versionado semántico](https://semver.org/lang/es/). Un cambio que rompa la API pública espera a la siguiente versión mayor.

Las fallas de seguridad **no** se informan en un issue: vea [SECURITY.md](SECURITY.md).

## Publicar una versión (mantenedores)

1. Actualice `__version__` en `djauth/__init__.py`. Es la única fuente de la versión.
2. Pase las notas de "Sin publicar" en `CHANGELOG.md` a la versión nueva, con la fecha.
3. Haga commit en `main` y espere a que la CI quede en verde.
4. Cree la Release en GitHub con la etiqueta `vX.Y.Z`:

   ```bash
   gh release create vX.Y.Z --title "vX.Y.Z" --notes "Ver CHANGELOG.md"
   ```

El flujo `publish.yml` comprueba que la etiqueta coincida con la versión y construye el paquete. Luego lo publica en TestPyPI y después en PyPI, este último con aprobación manual en el entorno `pypi`. Al final adjunta los archivos a la Release. No hacen falta contraseñas ni tokens (*Trusted Publishing*).
