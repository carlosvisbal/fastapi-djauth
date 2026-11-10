# 13. Desde Django

## Equivalencias

| Django | fastapi-djauth |
|---|---|
| `django.contrib.auth` | `AuthKit(AuthSettings(...)).init()` + `kit.install(app)` |
| `DATABASES["default"]` | `AuthSettings(database={...})` (mismo formato) |
| `USERNAME_FIELD = "email"` | `AuthSettings(username_field="email")` |
| `AUTHENTICATION_BACKENDS` | `AuthSettings(authentication_backends=(...))` |
| `AbstractUser` / `AUTH_USER_MODEL` | `AuthSettings(user_mixin=MiPerfil)` |
| `Permission`, `Group` | Iguales: `app.codename`, grupos con permisos |
| `class Meta: permissions = [...]` | `AuthSettings(permissions={...})` o `kit.register_permissions(...)` |
| `@login_required` | `Depends(current_user)` |
| `@permission_required("a.b")` | `Depends(require_perm("a.b"))` |
| `@staff_member_required` | `Depends(require_staff)` |
| `request.user` | `user: AuthUser = Depends(current_user)` (o `optional_user`) |
| `user.has_perm`, `has_perms`, `has_module_perms`, `get_full_name` | Iguales |
| `authenticate(request, username=…, password=…)` | `kit.authenticate(username, password)` |
| `login(request, user)` / `logout(request)` | `POST /auth/api/login` / `POST /auth/api/logout` |
| `make_password`, `check_password` | `from djauth import make_password, check_password` (mismo formato) |
| `PasswordResetTokenGenerator` | `kit.make_reset_token(user_id)` |
| `AUTH_PASSWORD_VALIDATORS` | Los cuatro de Django, incluidos (`password_min_length`) |
| `manage.py createsuperuser` / `changepassword` | `djauth createsuperuser` / `changepassword` |
| Admin `/admin/` (usuarios y grupos) | `/auth/admin` |
| `LogEntry` | Registro de acciones (`/auth/api/log`) |
| `SESSION_COOKIE_AGE`, `SESSION_COOKIE_SECURE` | `session_cookie_age`, `session_cookie_secure` |
| `CSRF_TRUSTED_ORIGINS` | `trusted_origins` |

## Importar usuarios con su contraseña

Las contraseñas usan el mismo formato `pbkdf2_sha256$…` que Django (verificado con Django 6.0), así que se copian tal cual y los usuarios entran con su contraseña de siempre.

```python
# importar.py: lee los usuarios de Django y los crea en djauth con el mismo hash
import psycopg
from djauth import AuthKit, AuthSettings

kit = AuthKit(AuthSettings(database_url="sqlite:///auth.sqlite3")).init()
with psycopg.connect("postgresql://…/proyecto_django") as conn:
    rows = conn.execute(
        "SELECT username, password, email, first_name, last_name, is_active, is_staff, is_superuser FROM auth_user"
    ).fetchall()
for username, password, email, first, last, active, staff, superuser in rows:
    created = kit.create_user(username, None, email=email, first_name=first, last_name=last,
                              is_active=active, is_staff=staff, is_superuser=superuser, validate=False)
    with kit._db() as db:                       # copiar el hash tal cual (sin volver a cifrar)
        db.get(kit.models.User, created["id"]).password = password
        db.commit()
```

Los hashes con otros algoritmos (`argon2`, `bcrypt`) no se reconocen: esos usuarios necesitan un enlace para elegir contraseña nueva.

## Diferencias

- No hay migraciones: `init()` crea las tablas y agrega columnas nuevas. Para renombrar o borrar, use Alembic.
- Los backends reciben `request` con `ip`, `user_agent` y `headers` (no el objeto `HttpRequest`).
- Un backend que falla se salta (Django propagaría la excepción).
- Sin permisos por objeto (`has_perm(perm, obj)`), sin envío de correos, sin "usuarios anónimos" con permisos.
- Más estricto que Django contra la escalada entre administradores (ver [Seguridad](10-seguridad.md)).
