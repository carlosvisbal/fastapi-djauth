"""Decoradores con los nombres de Django, para rutas de FastAPI.

    from djauth import login_required, permission_required

    @app.get("/perfil")
    @login_required
    def perfil(): ...

    @app.post("/pedidos/{id}/aprobar")
    @permission_required("ventas.aprobar_pedido")
    def aprobar(id: int): ...

El decorador va **debajo** de `@app.get(...)`, igual que en Django va debajo de la URL. Por dentro
añade la dependencia equivalente (`current_user`, `require_perm`…), así que se comporta exactamente
igual: 401 sin sesión, 403 sin permiso, y aparece en la documentación de `/docs`.

Si la función necesita el usuario, pídalo como siempre: `user: AuthUser = Depends(current_user)`.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import Depends

from djauth.api import current_user, require_perm, require_staff, require_superuser
from djauth.core import AuthUser
from djauth.errors import PermissionDeniedError

F = TypeVar("F", bound=Callable[..., Any])
_PARAM = "_djauth_guard"


def _guard(dependency: Callable[..., Any]) -> Callable[[F], F]:
    """Decorador que añade `dependency` a la ruta sin cambiar lo que recibe la función."""

    def decorator(func: F) -> F:
        if not callable(func) or isinstance(func, type):
            raise TypeError(
                "Use el decorador sobre una función de ruta: @login_required (sin paréntesis) o @permission_required('app.perm')"
            )
        signature = inspect.signature(func)
        params = list(signature.parameters.values())
        # Cada decorador apilado añade su propio parámetro (_djauth_guard, _djauth_guard_1…).
        name = _PARAM
        while name in signature.parameters:
            name = f"{name}_"
        guard = inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=Depends(dependency), annotation=Any)
        position = next((i for i, p in enumerate(params) if p.kind is inspect.Parameter.VAR_KEYWORD), len(params))
        params.insert(position, guard)

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                kwargs.pop(name, None)
                return await func(*args, **kwargs)

        else:

            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                kwargs.pop(name, None)
                return func(*args, **kwargs)

        wrapper.__signature__ = signature.replace(parameters=params)  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator


def login_required(func: F) -> F:
    """Como `@login_required` de Django: 401 si no hay sesión ni token válido."""
    return _guard(current_user)(func)


def permission_required(*perms: str) -> Callable[[F], F]:
    """Como `@permission_required` de Django: exige todos los permisos (`"app.codename"`).

    Acepta varios: `@permission_required("ventas.view_pedido", "ventas.change_pedido")`, o una lista.
    """
    if len(perms) == 1 and isinstance(perms[0], list | tuple | set):
        perms = tuple(perms[0])
    if not perms or not all(isinstance(p, str) and "." in p for p in perms):
        raise TypeError('Indique permisos con el formato "app.codename": @permission_required("ventas.aprobar_pedido")')
    return _guard(require_perm(*perms))


def staff_member_required(func: F) -> F:
    """Como `@staff_member_required` de Django: solo personal con acceso a la administración."""
    return _guard(require_staff)(func)


def superuser_required(func: F) -> F:
    """Solo superusuarios."""
    return _guard(require_superuser)(func)


def user_passes_test(
    test: Callable[[AuthUser], bool],
    message: str = "No cumple las condiciones para entrar aquí.",
    *,
    hint: str = "",
    code: str = "test_failed",
) -> Callable[[F], F]:
    """Como `@user_passes_test` de Django: la ruta exige que `test(user)` sea verdadero.

    @user_passes_test(lambda u: u.email.endswith("@empresa.com"), "Solo cuentas de la empresa.")
    """

    def check(user: AuthUser = Depends(current_user)) -> AuthUser:
        if not test(user):
            raise PermissionDeniedError(message, hint=hint, code=code)
        return user

    return _guard(check)
