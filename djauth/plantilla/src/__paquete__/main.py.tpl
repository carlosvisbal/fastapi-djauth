"""Punto de entrada: `uvicorn __paquete__.main:create_app --factory`."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from __paquete__ import __version__
from __paquete__.api.router import api_router
from __paquete__.core.config import Settings, get_settings
from __paquete__.core.security import build_auth
from __paquete__.db import build_engine, build_session_factory

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title=settings.name,
        version=__version__,
        # En producción no se publica la documentación interactiva.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    engine = build_engine(settings.database_url)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)

    app.include_router(api_router)

    @app.get("/health", tags=["sistema"], summary="Sonda de salud (pública)")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # Seguro por defecto: toda ruta exige sesión o token, salvo las exentas. Los permisos de cada
    # ruta se piden con require_perm(...) en el endpoint.
    build_auth(settings).install(app, protect=True, exempt={"/health"})

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    return app
