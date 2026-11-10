from __future__ import annotations


class AuthError(Exception):
    """Base de los errores del módulo."""


class ValidationError(AuthError):
    """Datos no válidos. `errors` asocia cada campo con sus mensajes (como los formularios de Django)."""

    def __init__(self, errors: dict[str, list[str]] | str) -> None:
        self.errors = {"__all__": [errors]} if isinstance(errors, str) else errors
        super().__init__(self.first)

    @property
    def first(self) -> str:
        return next((msgs[0] for msgs in self.errors.values() if msgs), "Datos no válidos.")


class NotFoundError(AuthError):
    pass


class PermissionDeniedError(AuthError):
    pass


class InvalidCredentialsError(AuthError):
    pass


class TooManyAttemptsError(AuthError):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(f"Demasiados intentos fallidos. Espere {max(1, retry_after // 60)} min e inténtelo de nuevo.")
