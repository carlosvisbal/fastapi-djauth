"""djauth: usuarios, grupos (roles), permisos y administración al estilo de Django, para FastAPI.

from djauth import AuthKit, AuthSettings, current_user, require_perm

kit = AuthKit(AuthSettings(database_url="sqlite:///auth.sqlite3")).init()
kit.install(app, protect=True)
"""

from djauth.api import (
    AuthMiddleware,
    Rule,
    current_user,
    identify,
    optional_user,
    require_perm,
    require_staff,
    require_superuser,
    rule,
    ws_user,
)
from djauth.core import SERVICE_USER, AuthKit, AuthUser
from djauth.errors import (
    AuthError,
    InvalidCredentialsError,
    NotFoundError,
    PermissionDeniedError,
    TooManyAttemptsError,
    ValidationError,
)
from djauth.hashers import check_password, make_password
from djauth.settings import AuthSettings, ExtraField

__version__ = "1.0.0"

__all__ = [
    "SERVICE_USER",
    "AuthError",
    "AuthKit",
    "AuthMiddleware",
    "AuthSettings",
    "AuthUser",
    "ExtraField",
    "InvalidCredentialsError",
    "NotFoundError",
    "PermissionDeniedError",
    "Rule",
    "TooManyAttemptsError",
    "ValidationError",
    "__version__",
    "check_password",
    "current_user",
    "identify",
    "make_password",
    "optional_user",
    "require_perm",
    "require_staff",
    "require_superuser",
    "rule",
    "ws_user",
]
