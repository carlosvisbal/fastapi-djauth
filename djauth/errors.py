"""Errores del módulo. Todos llevan:

- `code`: identificador fijo para programas (`"invalid_credentials"`, `"permission_denied"`…);
- `message`: explicación para la persona;
- `hint`: qué hacer para resolverlo (puede estar vacío);
- `status`: código HTTP con el que responde la API.

La API los devuelve así (ver docs/errores.md):

    {"detail": "Usuario o contraseña incorrectos.", "code": "invalid_credentials",
     "hint": "Revise mayúsculas y el teclado numérico…", "errors": {}}
"""

from __future__ import annotations

from typing import Any


class AuthError(Exception):
    """Base de los errores del módulo."""

    code = "auth_error"
    status = 400
    default_message = "No se pudo completar la operación."
    default_hint = ""

    def __init__(self, message: str | None = None, *, hint: str | None = None, code: str | None = None) -> None:
        self.message = message or self.default_message
        self.hint = self.default_hint if hint is None else hint
        if code:
            self.code = code
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {"detail": self.message, "code": self.code, "hint": self.hint, "errors": {}}


class ValidationError(AuthError):
    """Datos no válidos. `errors` asocia cada campo con sus mensajes (como los formularios de Django);
    los errores que no son de un campo van en `"__all__"`."""

    code = "validation_error"
    status = 400
    default_message = "Hay datos no válidos."
    default_hint = "Corrija los campos marcados y vuelva a enviar."

    def __init__(self, errors: dict[str, list[str]] | str, *, hint: str | None = None, code: str | None = None) -> None:
        self.errors = {"__all__": [errors]} if isinstance(errors, str) else errors
        super().__init__(self.first, hint=hint, code=code)

    @property
    def first(self) -> str:
        # El primer mensaje, tal cual: el campo al que pertenece va en `errors`.
        for messages in self.errors.values():
            if messages:
                return messages[0]
        return self.default_message

    def to_dict(self) -> dict[str, Any]:
        return {**super().to_dict(), "errors": self.errors}


class NotFoundError(AuthError):
    code = "not_found"
    status = 404
    default_message = "El elemento no existe."
    default_hint = "Puede que otra persona lo haya eliminado. Recargue la lista."


class PermissionDeniedError(AuthError):
    code = "permission_denied"
    status = 403
    default_message = "No tiene permiso para esta acción."
    default_hint = "Pida a un administrador el permiso necesario o el rol que lo incluye."


class InvalidCredentialsError(AuthError):
    code = "invalid_credentials"
    status = 401
    # Mismo mensaje si el usuario no existe o la contraseña es errónea: no revela qué usuarios hay.
    default_message = "Usuario o contraseña incorrectos."
    default_hint = (
        "Revise mayúsculas y el bloqueo numérico. Si olvidó la contraseña, pida a un administrador un enlace para restablecerla."
    )


class NotAuthenticatedError(AuthError):
    code = "not_authenticated"
    status = 401
    default_message = "No ha iniciado sesión o su sesión caducó."
    default_hint = "Inicie sesión de nuevo (o envíe un token válido en `Authorization: Bearer`)."


class TooManyAttemptsError(AuthError):
    code = "too_many_attempts"
    status = 429

    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(1, int(retry_after))
        minutes = max(1, round(self.retry_after / 60))
        super().__init__(
            f"Demasiados intentos fallidos. Espere {minutes} min e inténtelo de nuevo.",
            hint="El bloqueo es temporal y protege la cuenta contra ataques. Si no fue usted, avise a un administrador.",
        )

    def to_dict(self) -> dict[str, Any]:
        return {**super().to_dict(), "retry_after": self.retry_after}
