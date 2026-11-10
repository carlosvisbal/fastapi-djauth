"""Contraseñas con PBKDF2-SHA256 en el mismo formato que Django: `pbkdf2_sha256$iter$sal$hash`.

Al usar el mismo formato, los usuarios de un proyecto Django se pueden importar con su contraseña.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import string

ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 1_200_000
UNUSABLE_PREFIX = "!"
_SALT_CHARS = string.ascii_letters + string.digits


def _pbkdf2(password: str, salt: str, iterations: int) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return base64.b64encode(digest).decode("ascii")


def make_password(password: str | None, iterations: int = DEFAULT_ITERATIONS, salt: str | None = None) -> str:
    """Devuelve la contraseña cifrada. `None` produce una contraseña inutilizable (no permite entrar)."""
    if password is None:
        return UNUSABLE_PREFIX + "".join(secrets.choice(_SALT_CHARS) for _ in range(40))
    salt = salt or "".join(secrets.choice(_SALT_CHARS) for _ in range(22))
    return f"{ALGORITHM}${iterations}${salt}${_pbkdf2(password, salt, iterations)}"


def is_password_usable(encoded: str | None) -> bool:
    return bool(encoded) and not encoded.startswith(UNUSABLE_PREFIX)


def check_password(password: str, encoded: str | None) -> bool:
    if not is_password_usable(encoded):
        return False
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != ALGORITHM:
            return False
        return hmac.compare_digest(_pbkdf2(password, salt, int(iterations)), expected)
    except ValueError:
        return False


def must_update(encoded: str, iterations: int = DEFAULT_ITERATIONS) -> bool:
    """True si la contraseña se guardó con menos iteraciones que las actuales (se recifra al entrar)."""
    try:
        return int(encoded.split("$", 3)[1]) < iterations
    except (ValueError, IndexError):
        return False
