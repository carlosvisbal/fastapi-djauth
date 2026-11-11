# Política de seguridad

## Versiones con soporte

| Versión | Soporte |
|---|---|
| 1.3.x | Sí |
| < 1.3 | No: actualice a la última versión (1.1.0 corrigió el secuestro de WebSocket entre sitios) |

## Informar una vulnerabilidad

**No abra un issue público.** Use el aviso privado de GitHub: pestaña **Security → Report a vulnerability** en https://github.com/carlosvisbal/fastapi-djauth/security/advisories/new

Incluya, si puede: versión afectada, pasos para reproducirlo y el impacto. Recibirá respuesta en un plazo de 7 días. Una vez corregido, se publica una versión nueva y un aviso con el crédito a quien lo informó (si lo desea).

Lo que protege el módulo y sus límites: [docs/10-seguridad.md](docs/10-seguridad.md).

## Cómo se protege la cadena de publicación

- Los paquetes se publican desde GitHub Actions con *Trusted Publishing*: no existen contraseñas ni tokens de PyPI que robar.
- Cada versión en PyPI lleva una atestación firmada (PEP 740) que prueba de qué repositorio y flujo salió.
- Las acciones de GitHub están fijadas por commit, y Dependabot propone sus actualizaciones.
- En cada cambio se ejecutan pruebas, análisis de tipos (`mypy`), análisis de seguridad del código (`bandit`) y la búsqueda de vulnerabilidades conocidas en las dependencias (`pip-audit`).
