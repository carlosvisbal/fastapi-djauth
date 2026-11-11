# Copie este archivo a .env (djauth startproject ya lo hizo con valores seguros) y nunca suba .env al repositorio.
APP_NAME=__nombre__
APP_ENVIRONMENT=desarrollo
APP_DATABASE_URL=__database_url__
# Genere una con: python -c "import secrets; print(secrets.token_urlsafe(48))"
APP_SECRET_KEY=
# Superusuario inicial (se crea solo si la base no tiene usuarios)
APP_ADMIN_USERNAME=admin
APP_ADMIN_PASSWORD=
APP_ADMIN_EMAIL=
# Producción con HTTPS / detrás de un proxy
APP_COOKIE_SECURE=false
APP_TRUST_PROXY_HEADERS=false
APP_CORS_ORIGINS=[]
__env_db__
