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
from djauth.backends import AllowAllUsersModelBackend, AuthRequest, BaseBackend, ModelBackend
from djauth.core import SERVICE_USER, AuthKit, AuthUser
from djauth.database import DatabaseConfigError, url_from_django
from djauth.decorators import login_required, permission_required, staff_member_required, superuser_required, user_passes_test
from djauth.errors import (
    AuthError,
    InvalidCredentialsError,
    NotAuthenticatedError,
    NotFoundError,
    PermissionDeniedError,
    TooManyAttemptsError,
    ValidationError,
)
from djauth.hashers import check_password, make_password
from djauth.routers import BaseRouter, Databases, ModelMeta, RoutingSession, model_meta
from djauth.settings import AuthSettings, ExtraField

__version__ = "1.4.0"

__all__ = [
    "SERVICE_USER",
    "AllowAllUsersModelBackend",
    "AuthError",
    "AuthKit",
    "AuthMiddleware",
    "AuthRequest",
    "AuthSettings",
    "AuthUser",
    "BaseBackend",
    "BaseRouter",
    "DatabaseConfigError",
    "Databases",
    "ExtraField",
    "InvalidCredentialsError",
    "ModelBackend",
    "ModelMeta",
    "NotAuthenticatedError",
    "NotFoundError",
    "PermissionDeniedError",
    "RoutingSession",
    "Rule",
    "TooManyAttemptsError",
    "ValidationError",
    "__version__",
    "check_password",
    "current_user",
    "identify",
    "login_required",
    "make_password",
    "model_meta",
    "optional_user",
    "permission_required",
    "require_perm",
    "require_staff",
    "require_superuser",
    "rule",
    "staff_member_required",
    "superuser_required",
    "url_from_django",
    "user_passes_test",
    "ws_user",
]
