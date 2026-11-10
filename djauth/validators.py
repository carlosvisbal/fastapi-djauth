"""Validadores de nombre de usuario y de contraseña (los mismos criterios por defecto de Django)."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from djauth.errors import ValidationError

USERNAME_RE = re.compile(r"^[\w.@+-]+\Z")
USERNAME_MAX = 150
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+\Z")

# Las contraseñas más usadas (Django trae una lista de 20 000; esta cubre las más frecuentes).
COMMON_PASSWORDS = frozenset(
    [
        "123456",
        "123456789",
        "12345678",
        "12345",
        "1234567",
        "1234567890",
        "password",
        "password1",
        "password123",
        "qwerty",
        "qwerty123",
        "qwertyuiop",
        "abc123",
        "111111",
        "123123",
        "000000",
        "iloveyou",
        "admin",
        "admin123",
        "administrador",
        "welcome",
        "welcome1",
        "monkey",
        "dragon",
        "letmein",
        "football",
        "baseball",
        "master",
        "sunshine",
        "princess",
        "shadow",
        "superman",
        "michael",
        "654321",
        "1q2w3e4r",
        "1qaz2wsx",
        "zaq12wsx",
        "asdfghjkl",
        "zxcvbnm",
        "passw0rd",
        "p@ssw0rd",
        "contraseña",
        "contrasena",
        "clave123",
        "clave1234",
        "usuario",
        "usuario123",
        "hola1234",
        "hola12345",
        "colombia",
        "colombia123",
        "12341234",
        "11111111",
        "00000000",
        "87654321",
        "changeme",
        "cambiame",
        "temporal",
        "temporal123",
        "secreto",
        "secret",
        "test1234",
        "prueba123",
        "a1b2c3d4",
        "abcd1234",
        "qazwsxedc",
        "trustno1",
        "starwars",
        "whatever",
        "freedom",
    ]
)


def validate_username(username: str) -> str:
    username = (username or "").strip()
    if not username:
        raise ValidationError({"username": ["Este campo es obligatorio."]})
    if len(username) > USERNAME_MAX:
        raise ValidationError({"username": [f"Máximo {USERNAME_MAX} caracteres."]})
    if not USERNAME_RE.match(username):
        raise ValidationError({"username": ["Solo letras, números y los símbolos @ . + - _"]})
    return username


def normalize_email(email: str | None) -> str:
    """Como `BaseUserManager.normalize_email`: el dominio en minúsculas."""
    email = (email or "").strip()
    if not email:
        return ""
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise ValidationError({"email": ["Escriba una dirección de correo válida."]})
    local, _, domain = email.rpartition("@")
    return f"{local}@{domain.lower()}"


def password_help_texts(min_length: int) -> list[str]:
    return [
        "No puede parecerse demasiado a sus otros datos personales.",
        f"Debe tener al menos {min_length} caracteres.",
        "No puede ser una contraseña de uso común.",
        "No puede ser solo números.",
    ]


def validate_password(password: str, *, min_length: int = 8, user_attributes: tuple[str, ...] = ()) -> None:
    """Lanza `ValidationError({"password": [...]})` con todos los motivos por los que no es válida."""
    errors: list[str] = []
    if len(password) < min_length:
        errors.append(f"La contraseña es muy corta: debe tener al menos {min_length} caracteres.")
    if password.lower().strip() in COMMON_PASSWORDS:
        errors.append("Esta contraseña es demasiado común.")
    if password.isdigit():
        errors.append("La contraseña no puede ser solo números.")
    lowered = password.lower()
    for value in user_attributes:
        value = (value or "").lower()
        parts = [value, *re.split(r"\W+", value)]
        if any(len(p) >= 3 and SequenceMatcher(a=lowered, b=p).quick_ratio() >= 0.7 for p in parts):
            errors.append("La contraseña se parece demasiado a sus datos personales.")
            break
    if errors:
        raise ValidationError({"password": errors})
