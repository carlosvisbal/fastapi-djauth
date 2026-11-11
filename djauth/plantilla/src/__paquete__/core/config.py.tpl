"""Configuración: variables de entorno con prefijo APP_ (o el archivo .env). Ver .env.example."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    name: str = "__nombre__"
    environment: Literal["desarrollo", "produccion"] = "desarrollo"

    # Una sola base para los datos de la aplicación y los usuarios (tablas auth_*).
    database_url: str = "__database_url__"

    # Firma los enlaces de restablecimiento de contraseña. Obligatoria: sin valor, la aplicación no arranca.
    secret_key: SecretStr

    # Superusuario que se crea al primer arranque, si la base no tiene usuarios.
    admin_username: str = "admin"
    admin_password: SecretStr | None = None
    admin_email: str = ""

    # Producción detrás de HTTPS / proxy.
    cookie_secure: bool = False
    trust_proxy_headers: bool = False
    cors_origins: list[str] = []

    @property
    def is_production(self) -> bool:
        return self.environment == "produccion"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # los valores vienen del entorno (APP_*) o de .env
