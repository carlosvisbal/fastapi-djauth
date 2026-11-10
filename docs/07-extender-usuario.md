# 7. Extender el usuario

Dos formas, combinables:

| | Columnas propias (`user_mixin`) | Campos JSON (`extra_fields`) |
|---|---|---|
| Equivale a | Heredar de `AbstractUser` en Django | Un campo JSON con formulario |
| Se guarda en | Columnas reales de la tabla | La columna `extra` |
| Consultar o filtrar en SQL | Sí | Limitado |
| Cambia la tabla | Sí (columnas nuevas se agregan solas) | No |
| Se lee como | `user.telefono` | `user.extra["sede"]` |

## Columnas propias (recomendado)

```python
from datetime import date
from sqlalchemy import Boolean, Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

class Perfil:
    telefono: Mapped[str] = mapped_column(String(20), default="", info={"label": "Teléfono"})
    sede: Mapped[str | None] = mapped_column(
        String(30), nullable=True,
        info={"label": "Sede", "choices": ["Norte", "Sur"], "required": True},
    )
    turno: Mapped[int | None] = mapped_column(Integer, nullable=True, info={"help_text": "1, 2 o 3"})
    es_supervisor: Mapped[bool] = mapped_column(Boolean, default=False)
    ingreso: Mapped[date | None] = mapped_column(Date, nullable=True)
    codigo_erp: Mapped[str | None] = mapped_column(String(20), nullable=True, info={"editable": False})

kit = AuthKit(AuthSettings(user_mixin=Perfil, ...)).init()
```

Listo: las columnas existen en la tabla, se aceptan en la API (`POST/PATCH /auth/api/users` como claves de primer nivel), aparecen en el formulario de la administración y se leen como `user.telefono`.

### Opciones de `info`

| Clave | Para |
|---|---|
| `label` | Texto en el formulario (por defecto, el nombre de la columna). |
| `help_text` | Ayuda bajo el campo. |
| `choices` | Lista de valores permitidos (se muestra como lista desplegable). |
| `required` | Obligatorio al crear (por defecto: si la columna no admite nulos y no tiene valor por defecto). |
| `editable` | `False` = solo lectura en la API y la administración (se llena por código). |

### Tipos que entiende el formulario

`String`/`Text` → texto (con su longitud máxima), `Integer` → entero, `Float`/`Numeric` → número, `Boolean` → casilla, `Date` → fecha, `DateTime` → fecha y hora, `Enum` o `choices` → lista. Otros tipos (JSON, binarios) se pueden declarar pero solo se editan por código.

### Agregar columnas después

Al arrancar, `init()` **agrega** a la tabla las columnas nuevas y aplica su valor por defecto a los usuarios existentes. No renombra ni borra columnas: para eso use una herramienta de migraciones (Alembic) sobre las tablas `auth_*`. Declare las columnas nuevas con `default=` o `nullable=True`.

## Campos JSON (sin tocar la tabla)

```python
from djauth import ExtraField

AuthSettings(extra_fields=(
    ExtraField("sede", "Sede", "choice", ("Norte", "Sur"), required=True),
    ExtraField("turno", "Turno", "number", help_text="1, 2 o 3"),
    ExtraField("supervisor", "Es supervisor", "bool"),
))
```

Tipos: `text`, `number`, `bool`, `choice`. Se envían en la API dentro de `"extra": {...}`.

## Desde código

```python
kit.create_user("op", "Clave-Segura-2026", fields={"telefono": "+1 555 0100", "sede": "Sur"})
kit.update_user(user_id, {"es_supervisor": True})
```
