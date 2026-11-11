"""Usuarios, roles y permisos con fastapi-djauth.

Agregue aquí los permisos de cada módulo nuevo ("app.codename") y los roles que los agrupan. Los roles
se crean una sola vez: lo que se ajuste después en /auth/admin se respeta.
"""

from __future__ import annotations

from djauth import AuthKit, AuthSettings

from __paquete__.core.config import Settings

PERMISSIONS: dict[str, dict[str, str]] = {
    "inventario": {
        "view_producto": "Puede ver productos",
        "add_producto": "Puede agregar productos",
        "change_producto": "Puede modificar productos",
        "delete_producto": "Puede eliminar productos",
    },
}

ROLES: dict[str, list[str]] = {
    "Lector": ["inventario.view_producto"],
    "Editor": [
        "inventario.view_producto",
        "inventario.add_producto",
        "inventario.change_producto",
        "inventario.delete_producto",
    ],
}


def build_auth(settings: Settings) -> AuthKit:
    admin_password = settings.admin_password.get_secret_value() if settings.admin_password else ""
    bootstrap = (settings.admin_username, admin_password, settings.admin_email) if admin_password else None
    kit = AuthKit(
        AuthSettings(
            database_url=settings.database_url,
            site_name=settings.name,
            home_url="/docs" if not settings.is_production else "/",
            secret_key=settings.secret_key.get_secret_value(),
            session_cookie_secure=settings.cookie_secure,
            trust_proxy_headers=settings.trust_proxy_headers,
            permissions=PERMISSIONS,
            bootstrap_superuser=bootstrap,
        )
    ).init()
    for name, perms in ROLES.items():
        kit.ensure_group(name, perms)
    return kit
