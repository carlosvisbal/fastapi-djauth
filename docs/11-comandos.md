# 11. Comandos

Al instalar el paquete queda el comando `djauth` (también `python -m djauth`).

```bash
djauth --db sqlite:///auth.sqlite3 createsuperuser --username admin --email admin@example.com
djauth --db sqlite:///auth.sqlite3 changepassword admin
djauth --db sqlite:///auth.sqlite3 listusers
```

| Comando | Qué hace |
|---|---|
| `createsuperuser --username U [--email E]` | Crea un superusuario. Valida la contraseña. |
| `changepassword U` | Cambia la contraseña y cierra las sesiones abiertas de ese usuario. |
| `listusers` | Lista usuarios con marcas: `S` superusuario, `A` acceso a la administración, `-` inactivo. |

| Opción | Por defecto | Qué es |
|---|---|---|
| `--db` | `$DJAUTH_DATABASE_URL` o `sqlite:///auth.sqlite3` | URL de la base. |
| `--prefix` | `auth_` | Prefijo de las tablas (si cambió `table_prefix`). |

La contraseña se pide por teclado (sin mostrarla). En scripts o CI, use la variable `DJAUTH_PASSWORD`.

## En Docker

```bash
docker compose exec web djauth --db sqlite:////app/data/auth.sqlite3 createsuperuser --username admin
```
