# 4. Sesión o token Bearer

Puede usar uno, otro o los dos (por defecto, los dos).

| | Sesión (cookie) | Bearer |
|---|---|---|
| Para | Navegadores, paneles web | APIs, apps móviles, integraciones, scripts |
| Activar | `enable_sessions=True` | `enable_bearer=True` |
| Obtener | `POST /auth/api/login` | `POST /auth/api/token` |
| Enviar | La cookie va sola | `Authorization: Bearer <token>` |
| WebSocket | La cookie va sola | `?access_token=<token>` |
| Duración | `session_cookie_age` (2 semanas) | `bearer_token_age` (12 h) |
| CSRF | Protegido (ver [Seguridad](10-seguridad.md)) | No aplica |

## Solo cookie (sitio web tradicional)

```python
AuthSettings(enable_bearer=False)
```

## Solo Bearer (API pura, app móvil)

```python
AuthSettings(enable_sessions=False)
```

Las páginas de administración siguen funcionando: guardan el token en la pestaña (`sessionStorage`) y lo envían como Bearer.

## Obtener y usar un token

```bash
curl -X POST http://localhost:8000/auth/api/token \
     -H "Content-Type: application/json" \
     -d '{"username": "mes", "password": "Clave-Del-Sistema-1"}'
# {"access_token": "…", "token_type": "bearer", "expires_in": 43200, "user": {…}}

curl http://localhost:8000/pedidos -H "Authorization: Bearer …"
```

```python
import httpx
token = httpx.post(f"{URL}/auth/api/token", json={"username": "mes", "password": "…"}).json()["access_token"]
httpx.get(f"{URL}/pedidos", headers={"Authorization": f"Bearer {token}"})
```

El botón **Authorize** de `/docs` (Swagger) también funciona: pida usuario y contraseña y guarda el token.

## Revocar

- `POST /auth/api/logout` con el token lo revoca al instante.
- Cambiar la contraseña revoca todas las demás sesiones y tokens del usuario.
- Desactivar al usuario o pulsar "Cerrar sus sesiones" en la administración los revoca todos.

Los tokens **no son JWT**: son aleatorios, se guardan solo como hash SHA-256 y se pueden revocar. Una copia de la base de datos no sirve para suplantar a nadie.
