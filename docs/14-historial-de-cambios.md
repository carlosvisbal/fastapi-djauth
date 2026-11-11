# 14. Historial de cambios del usuario

Registro dedicado **solo a los cambios de los datos del usuario**: quién cambió qué campo, de qué valor a cuál, cuándo, desde qué IP y por qué. Está activo por defecto y no hay que escribir código para usarlo.

```text
11/11/26 08:15  ana   Modificación  Nombre: — → Ana            admin   Ascenso · 10.0.0.25
                                    Acceso a la administración: No → Sí
                                    Grupos: Operador → Supervisor
```

## Qué se registra y qué no

| Se registra | Acción | Qué guarda |
|---|---|---|
| Alta de un usuario | `create` | Los valores iniciales de cada campo |
| Modificación | `update` | Solo los campos que cambiaron: valor anterior y nuevo |
| Cambio de contraseña | `password` | Que cambió, **nunca** la contraseña ni su hash |
| Eliminación | `delete` | Los últimos valores que tenía |
| Eliminación de un grupo | `update` | En cada miembro: el grupo que perdió |

Campos que sigue: usuario, correo, nombre, apellidos, activo, acceso a la administración, superusuario, grupos, permisos individuales, contraseña, las [columnas propias](07-extender-usuario.md) y los campos JSON (`extra.<nombre>`).

**No** se registra (va en el registro general, pestaña *Registro*): inicios de sesión, cierres de sesión, enlaces de restablecimiento generados ni cambios de grupos y roles. Tampoco `last_login` ni guardar sin cambiar nada.

## Garantías

- **Atómico:** el registro se guarda en la misma transacción que el cambio. O quedan los dos, o ninguno.
- **Sobrevive a la eliminación:** el historial no depende de que el usuario exista (no hay clave foránea). Puede consultar los datos de un usuario eliminado.
- **Solo lectura:** la API no tiene rutas para modificar ni borrar el historial.
- **Datos protegidos:** las contraseñas nunca se guardan, y los campos marcados como sensibles registran que cambiaron, sin los valores (ver abajo).

## El motivo del cambio

Cada cambio puede llevar un motivo, que queda en el historial:

- **Administración web:** campo *Motivo del cambio* en el formulario del usuario.
- **API:** parámetro `?reason=` en crear, modificar, eliminar y asignar contraseña.

  ```http
  PATCH /auth/api/users/7?reason=Cambio%20de%20área
  ```

- **Código:** argumento `reason=` en `create_user`, `update_user`, `delete_user` y `set_password`.

  ```python
  kit.update_user(7, {"is_active": False}, actor=admin, reason="Retiro de la empresa")
  ```

Algunos cambios traen el motivo puesto: *Cambiada por el propio usuario*, *Restablecida con un enlace*, *Sincronizado desde un backend de autenticación*, *Se eliminó el grupo X*…

## Quién y desde dónde

- **Quién (`actor`):** el usuario que hizo el cambio. Sale `sistema` cuando se hace por código sin `actor=` (scripts, tareas, el superusuario inicial). Una llave de API figura como `api-key`.
- **IP:** la de la petición que hizo el cambio, tomada automáticamente en las rutas de la API. Detrás de un proxy, active `trust_proxy_headers` para guardar la IP real del cliente. Por código queda vacía.

## Campos sensibles

Para datos personales (cédula, salario…) marque el campo como sensible. El historial anota que cambió, sin guardar los valores:

```python
class Perfil:
    cedula: Mapped[str] = mapped_column(String(20), default="", info={"label": "Cédula", "sensitive": True})

AuthSettings(
    user_mixin=Perfil,
    extra_fields=(ExtraField("salario", "Salario", "number", sensitive=True),),
)
```

En el historial aparece como `{"cedula": {"hidden": true}}`.

## Consultar

**Administración web:** pestaña *Cambios de usuarios* (filtros por acción y campo), o el botón *Historial de cambios* en la ficha del usuario.

**API** (requiere el permiso `auth.view_userchange`, además de ser personal):

```http
GET /auth/api/user-history?user_id=7&action=update&field=email&since=2026-11-01&limit=50
GET /auth/api/users/7/history
```

```json
{
  "items": [
    {
      "id": 42, "changed_at": "2026-11-11T08:15:00", "user_id": 7, "user": "ana",
      "action": "update",
      "changes": {"first_name": {"old": "", "new": "Ana"}, "groups": {"old": ["Operador"], "new": ["Supervisor"]}},
      "actor_id": 1, "actor": "admin", "reason": "Ascenso", "ip": "10.0.0.25"
    }
  ],
  "total": 1, "limit": 50, "offset": 0
}
```

Filtros: `user_id`, `actor_id`, `action` (`create`, `update`, `password`, `delete`), `field` (`email`, `groups`, `password`, `extra.sede`…), `since` y `until` (fecha ISO). Del más reciente al más antiguo.

**Código:**

```python
items, total = kit.user_history(7, field="is_active", limit=20)
```

## Permiso

`auth.view_userchange` (*Puede ver el historial de cambios de usuarios*) es independiente de `auth.view_user`: puede dar acceso a un auditor sin que pueda modificar usuarios, o dejar que alguien administre usuarios sin ver el historial. Los superusuarios lo tienen siempre.

## Desactivarlo

```python
AuthSettings(user_history=False)
```

Los registros ya guardados se conservan. La tabla es `<table_prefix>user_history` (`auth_user_history` por defecto) y se crea sola al arrancar, también en bases existentes.
