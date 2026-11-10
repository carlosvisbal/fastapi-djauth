"""Columnas propias del usuario (`AuthSettings.user_mixin`): cómo se muestran y se validan.

Cada columna toma su configuración de `mapped_column(..., info={...})`:

    telefono: Mapped[str] = mapped_column(String(30), default="", info={"label": "Teléfono"})
    sede: Mapped[str | None] = mapped_column(String(30), nullable=True,
        info={"label": "Sede", "choices": ["Norte", "Sur"], "required": True})

Claves de `info`: `label`, `help_text`, `choices`, `required`, `editable` (False = solo lectura en la
administración y la API).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Enum, Float, Integer, Numeric, String, Text

from djauth.errors import ValidationError

# Columnas de la tabla base: no son "propias" aunque estén en el usuario.
BASE_COLUMNS = frozenset(
    {
        "id", "username", "password", "email", "first_name", "last_name", "is_active", "is_staff",
        "is_superuser", "last_login", "date_joined", "extra",
    }
)  # fmt: skip


@dataclass(frozen=True)
class UserField:
    name: str
    label: str
    type: str  # text | integer | number | bool | choice | date | datetime
    required: bool
    nullable: bool
    editable: bool
    max_length: int | None
    choices: tuple[str, ...]
    help_text: str

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "editable": self.editable,
            "max_length": self.max_length,
            "choices": list(self.choices),
            "help_text": self.help_text,
        }

    def clean(self, value: Any) -> Any:
        """Convierte el valor recibido (JSON) al tipo de la columna o lanza ValidationError."""

        def fail(message: str) -> ValidationError:
            return ValidationError({self.name: [message]})

        if value is None or (value == "" and self.type != "text"):
            if self.required:
                raise fail("Este campo es obligatorio.")
            if not self.nullable:
                return "" if self.type in ("text", "choice") else False if self.type == "bool" else None
            return None
        if self.type == "bool":
            if isinstance(value, bool):
                return value
            if str(value).lower() in ("true", "1", "sí", "si", "on"):
                return True
            if str(value).lower() in ("false", "0", "no", "off"):
                return False
            raise fail("Debe ser sí o no.")
        if self.type == "integer":
            try:
                if isinstance(value, float) and not value.is_integer():
                    raise ValueError
                return int(value)
            except (TypeError, ValueError):
                raise fail("Escriba un número entero.") from None
        if self.type == "number":
            try:
                return float(value)
            except (TypeError, ValueError):
                raise fail("Escriba un número.") from None
        if self.type in ("date", "datetime"):
            if isinstance(value, datetime):
                return value.date() if self.type == "date" else value
            if isinstance(value, date):
                return value if self.type == "date" else datetime.combine(value, datetime.min.time())
            try:
                parsed = datetime.fromisoformat(str(value))
            except ValueError:
                raise fail("Escriba una fecha válida (AAAA-MM-DD).") from None
            return parsed.date() if self.type == "date" else parsed
        text = str(value).strip()
        if self.required and not text:
            raise fail("Este campo es obligatorio.")
        if self.max_length and len(text) > self.max_length:
            raise fail(f"Máximo {self.max_length} caracteres.")
        if self.choices and text and text not in self.choices:
            raise fail(f"Elija una de: {', '.join(self.choices)}.")
        return text


def to_json(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date | datetime) else value


def user_fields(user_model: Any) -> tuple[UserField, ...]:
    """Columnas propias del modelo de usuario, en el orden en que se declararon."""
    out = []
    for column in user_model.__table__.columns:
        if column.name in BASE_COLUMNS:
            continue
        info = column.info or {}
        sql_type = column.type
        choices = tuple(str(c) for c in info.get("choices", ()))
        if isinstance(sql_type, Enum):
            kind, choices = "choice", choices or tuple(sql_type.enums)
        elif choices:
            kind = "choice"
        elif isinstance(sql_type, Boolean):
            kind = "bool"
        elif isinstance(sql_type, Integer):
            kind = "integer"
        elif isinstance(sql_type, Float | Numeric):
            kind = "number"
        elif isinstance(sql_type, DateTime):
            kind = "datetime"
        elif isinstance(sql_type, Date):
            kind = "date"
        elif isinstance(sql_type, String | Text):
            kind = "text"
        else:
            continue  # tipos que la administración no sabe editar (JSON, binarios…): solo por código
        has_default = column.default is not None or column.server_default is not None
        out.append(
            UserField(
                name=column.name,
                label=str(info.get("label") or column.name.replace("_", " ").capitalize()),
                type=kind,
                required=bool(info.get("required", not column.nullable and not has_default)),
                nullable=bool(column.nullable),
                editable=bool(info.get("editable", True)),
                max_length=getattr(sql_type, "length", None) if kind in ("text", "choice") else None,
                choices=choices,
                help_text=str(info.get("help_text", "")),
            )
        )
    return tuple(out)
