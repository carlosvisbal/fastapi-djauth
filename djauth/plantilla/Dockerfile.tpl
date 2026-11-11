# Imagen de producción: dependencias fijadas por uv.lock, usuario sin privilegios y sonda de salud.
FROM python:__python__-slim AS base
COPY --from=ghcr.io/astral-sh/uv:__uv__ /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_CACHE=1
WORKDIR /app

# 1) Solo dependencias (capa que se reutiliza mientras no cambie uv.lock).
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --no-editable

# 2) El código.
COPY README.md ./
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
RUN uv sync --locked --no-dev --no-editable

RUN useradd --create-home --uid 10001 app && mkdir -p /app/data && chown app /app/data
USER app
ENV PATH="/app/.venv/bin:$PATH" APP_ENVIRONMENT=produccion
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

# Aplica las migraciones pendientes y arranca. Detrás de un proxy, añada --proxy-headers.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn __paquete__.main:create_app --factory --host 0.0.0.0 --port 8000"]
