# 10. Seguridad

## Lista para producción

- [ ] Sirva el sitio por **HTTPS**. La cookie se marca `Secure` sola con HTTPS; con un proxy delante, active `trust_proxy_headers=True` (solo si el proxy es suyo).
- [ ] No deje la contraseña del superusuario inicial en el código: léala de una variable de entorno, o use `djauth createsuperuser`.
- [ ] Defina `secret_key` desde el entorno si tiene varias instancias del servicio (si no, cada base genera la suya y la guarda).
- [ ] Haga copias de seguridad de la base (contiene usuarios, roles y registro).
- [ ] Si tiene un frontend en otro dominio, agréguelo a `trusted_origins` (y configure CORS en FastAPI).

## Qué protege y cómo

| Riesgo | Protección |
|---|---|
| Robo de la base de datos | Contraseñas con PBKDF2-SHA256 (1 200 000 iteraciones, sal aleatoria). Sesiones y tokens guardados solo como hash SHA-256: copiarlos no sirve para entrar. |
| Fuerza bruta | Bloqueo temporal por usuario e IP tras `login_max_failures` intentos (`429` + `Retry-After`). |
| Saber qué usuarios existen | Mismo mensaje y mismo tiempo de respuesta si el usuario no existe o la contraseña es errónea. |
| Contraseñas débiles | Longitud mínima, lista de contraseñas comunes, no solo números, no parecida a sus datos. |
| CSRF | Las peticiones que modifican datos con cookie deben venir del mismo origen (`Origin` / `Sec-Fetch-Site`). Cookie `SameSite=Lax`. También el inicio de sesión. |
| Secuestro de WebSocket (CSWSH) | Un WebSocket autenticado con cookie debe abrirse desde el mismo origen. |
| Robo de cookie por XSS | Cookie `HttpOnly` (JavaScript no la lee). Páginas con `Content-Security-Policy` estricta: sin scripts en línea ni recursos externos. |
| Clickjacking | `X-Frame-Options: DENY` y `frame-ancestors 'none'`. |
| Fijación de sesión | Cada inicio de sesión crea una sesión nueva y descarta la anterior. |
| Sesiones que no se pueden cerrar | Tokens opacos (no JWT): cerrar sesión, cambiar contraseña o desactivar al usuario los revoca al instante. |
| Escalada de privilegios | Un administrador no superusuario no puede crear o tocar superusuarios, conceder permisos que no tiene, ni modificar a usuarios con más permisos. Siempre queda un superusuario activo. |
| Redirección abierta | `?next=` solo acepta rutas del mismo sitio. |
| Fuga del enlace de restablecimiento | Va en el fragmento (`#`): no llega al servidor ni a los logs. Un solo uso, caduca, `Referrer-Policy: no-referrer`. |
| Abuso de CPU | Contraseñas de más de `password_max_length` se rechazan sin cifrar. |
| Trazabilidad | Registro de acciones: quién creó, cambió o eliminó qué, inicios de sesión y cambios de contraseña. Historial de cambios de cada usuario, campo por campo. |
| Réplicas atrasadas (varias bases) | Contraseñas, sesiones y tokens se validan siempre en la base de escritura; ninguna base `READ_ONLY` recibe escrituras. [Guía](17-varias-bases-y-routers.md#seguros). |

## Límites que debe conocer

- **Varios procesos:** el bloqueo por intentos fallidos y la caché de sesiones (5 s) viven en la memoria de cada proceso. Con varios workers, el bloqueo es por proceso y una sesión revocada puede valer hasta 5 s en los demás. Para límites globales, ponga un limitador en el proxy (nginx `limit_req`, Traefik, Cloudflare).
- **Sin correo:** el módulo no envía correos; el enlace de restablecimiento lo genera un administrador.
- **Sin doble factor (2FA)** por ahora. Puede añadirlo con un backend propio ([Backends](06-backends.md)).

## Informar una vulnerabilidad

Ver [SECURITY.md](../SECURITY.md). No abra un issue público.
