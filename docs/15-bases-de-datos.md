# 15. Bases de datos: conexión por motor

Cómo conectar fastapi-djauth a cada motor, qué instalar, qué opciones sirven y en qué se diferencian. La configuración general está en [Configuración](02-configuracion.md#base-de-datos). Para usar varias bases a la vez (réplicas, una base por área), vea [Varias bases y routers](17-varias-bases-y-routers.md).

## Elegir un motor

| Motor | Instalar | Probado en la CI | Recomendado para |
|---|---|---|---|
| [SQLite](#sqlite) | Nada (viene con Python) | Sí, todas las pruebas | Desarrollo, pruebas, un solo servidor con poco tráfico |
| [PostgreSQL](#postgresql) | `fastapi-djauth[postgres]` | Sí, servidor real | **Producción** (la opción más completa) |
| [MySQL / MariaDB](#mysql-y-mariadb) | `fastapi-djauth[mysql]` | Sí, servidor real (MySQL 8.4) | Producción, si su empresa ya usa MySQL |
| [Oracle](#oracle) | `fastapi-djauth[oracle]` | Sí, servidor real (Oracle 23ai Free) | Empresas con Oracle |
| [SQL Server](#sql-server) | `fastapi-djauth[mssql]` | Sí, servidor real (SQL Server 2022) | Empresas con SQL Server |

Diferencias que importan:

| | SQLite | PostgreSQL | MySQL | Oracle | SQL Server |
|---|---|---|---|---|---|
| Correo único sin distinguir mayúsculas (con `username_field="email"`), garantizado por la base | Sí | Sí | Lo comprueba la aplicación | Lo comprueba la aplicación | Lo comprueba la aplicación |
| Varios servidores o procesos escribiendo a la vez | Limitado | Sí | Sí | Sí | Sí |
| Columnas propias nuevas agregadas solas al arrancar | Sí | Sí | Sí | Sí | Sí |

"Lo comprueba la aplicación" significa que, antes de guardar, el módulo busca si el correo ya existe. Basta en la práctica. Solo dos altas simultáneas con el mismo correo, en el mismo instante, podrían colarse, cosa que en PostgreSQL y SQLite impide un índice único.

## Dos formas de configurar

Con un diccionario (cada valor por separado, sin escapar nada):

```python
import os
from djauth import AuthKit, AuthSettings

kit = AuthKit(AuthSettings(database={
    "ENGINE": "postgresql",                 # postgresql | mysql | sqlite | oracle | mssql
    "NAME": "miapp",                        # nombre de la base (en SQLite: la ruta del archivo)
    "USER": "app",
    "PASSWORD": os.environ["DB_PASSWORD"],  # @ / # : y espacios funcionan tal cual
    "HOST": "db.empresa.local",
    "PORT": 5432,
    "OPTIONS": {"sslmode": "require"},      # parámetros del controlador (ver cada motor)
    "DRIVER": "psycopg",                    # opcional: forzar el controlador
})).init()
```

O con una URL de SQLAlchemy:

```python
AuthSettings(database_url="postgresql+psycopg://app:clave@db.empresa.local:5432/miapp?sslmode=require")
```

En la URL, los caracteres especiales de la contraseña deben ir escapados (`@` → `%40`). Por eso conviene el diccionario cuando la contraseña viene de una variable de entorno.

**Controlador síncrono.** El módulo usa SQLAlchemy síncrono y FastAPI ejecuta sus rutas en un pool de hilos. Use controladores síncronos (`psycopg`, `pymysql`, `oracledb`, `pyodbc`); un controlador asíncrono (`asyncpg`, `aiomysql`) se rechaza al arrancar. Su aplicación puede seguir usando uno asíncrono para sus propias consultas.

**Credenciales.** Nunca escriba la contraseña en el código: léala de una variable de entorno o de un gestor de secretos. Use un usuario de la base con permisos solo sobre la base de la aplicación, no el administrador del servidor.

## SQLite

No necesita servidor ni instalar nada.

```python
AuthSettings(database={"ENGINE": "sqlite", "NAME": "/var/lib/miapp/auth.sqlite3"})
# o
AuthSettings(database_url="sqlite:////var/lib/miapp/auth.sqlite3")   # 4 barras = ruta absoluta
AuthSettings(database_url="sqlite:///./auth.sqlite3")                # 3 barras = ruta relativa
```

- La carpeta se crea sola si no existe.
- `NAME` vacío o `":memory:"` crea una base **en memoria**, que se pierde al apagar. Sirve para pruebas.
- En Docker, guarde el archivo en un volumen (`/app/data/auth.sqlite3`); si no, se pierde al recrear el contenedor.

**Límites:** SQLite escribe de a una operación a la vez. Va bien con un proceso de uvicorn y poco tráfico de escritura; para varios procesos o servidores, use PostgreSQL o MySQL.

## PostgreSQL

```bash
pip install "fastapi-djauth[postgres]"     # instala psycopg 3
```

```python
AuthSettings(database={
    "ENGINE": "postgresql",
    "NAME": "miapp",
    "USER": "app",
    "PASSWORD": os.environ["DB_PASSWORD"],
    "HOST": "db.empresa.local",
    "PORT": 5432,
    "OPTIONS": {"sslmode": "verify-full", "sslrootcert": "/etc/ssl/certs/ca-empresa.pem"},
})
```

Opciones útiles en `OPTIONS` (son las de libpq):

| Opción | Para |
|---|---|
| `sslmode` | `require` (cifrado), `verify-full` (cifrado y comprueba el certificado del servidor: lo recomendado en producción) |
| `sslrootcert` | Certificado de la autoridad que firmó el del servidor |
| `connect_timeout` | Segundos de espera al conectar (p. ej. `10`) |
| `application_name` | Nombre que aparece en `pg_stat_activity` (p. ej. `"miapp-auth"`) |

- Si tiene instalado `psycopg2` en lugar de `psycopg`, se usa ese. Para forzarlo: `"DRIVER": "psycopg2"`.
- PostGIS: `"ENGINE": "postgresql"` (o el nombre de Django, `django.contrib.gis.db.backends.postgis`).
- Para que las tablas convivan con las de su aplicación sin chocar, cambie el prefijo: `table_prefix="seg_"` crea `seg_user`, `seg_group`…

Crear la base y el usuario (como administrador de PostgreSQL):

```sql
CREATE USER app WITH PASSWORD '…';
CREATE DATABASE miapp OWNER app;
```

## MySQL y MariaDB

```bash
pip install "fastapi-djauth[mysql]"        # instala PyMySQL
```

```python
AuthSettings(database={
    "ENGINE": "mysql",                      # también "mariadb"
    "NAME": "miapp",
    "USER": "app",
    "PASSWORD": os.environ["DB_PASSWORD"],
    "HOST": "db.empresa.local",
    "PORT": 3306,
    "OPTIONS": {"charset": "utf8mb4"},
})
```

Opciones útiles en `OPTIONS`:

| Opción | Para |
|---|---|
| `charset` | `utf8mb4`: tildes, ñ y cualquier carácter. No use `utf8` (en MySQL es incompleto). |
| `ssl_ca` | Ruta del certificado de la autoridad: activa la conexión cifrada y verifica el servidor |
| `ssl_cert`, `ssl_key` | Certificado de cliente, si el servidor lo exige |
| `connect_timeout` | Segundos de espera al conectar |

- Si tiene `mysqlclient` en lugar de PyMySQL, se usa ese. Para forzar uno: `"DRIVER": "mysqldb"` o `"DRIVER": "pymysql"`.
- MySQL cierra las conexiones inactivas tras `wait_timeout` (8 horas por defecto). El módulo renueva las suyas cada `database_conn_max_age` segundos (30 min) y verifica cada conexión antes de usarla, así que no verá el error "MySQL server has gone away".
- Las búsquedas de usuario ya ignoran mayúsculas en cualquier motor.

Crear la base y el usuario:

```sql
CREATE DATABASE miapp CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'app'@'%' IDENTIFIED BY '…';
GRANT ALL PRIVILEGES ON miapp.* TO 'app'@'%';
```

## Oracle

```bash
pip install "fastapi-djauth[oracle]"       # instala oracledb (modo "thin": no necesita Oracle Client)
```

```python
AuthSettings(database={
    "ENGINE": "oracle",
    "NAME": "ORCLPDB1",                     # nombre del SERVICIO (lo habitual: una PDB)
    "USER": "app",
    "PASSWORD": os.environ["DB_PASSWORD"],
    "HOST": "oracle.empresa.local",
    "PORT": 1521,
})
# Base antigua identificada por SID en lugar de servicio:
AuthSettings(database={"ENGINE": "oracle", "OPTIONS": {"sid": "ORCL"}, "USER": …, "PASSWORD": …, "HOST": …})
# Con URL:
AuthSettings(database_url="oracle+oracledb://app:clave@oracle.empresa.local:1521/?service_name=ORCLPDB1")
```

- `NAME` es el **nombre del servicio** (`FREEPDB1`, `ORCLPDB1`…), que es lo que usa toda base Oracle moderna. Si su DBA le da un SID, póngalo en `OPTIONS={"sid": …}`.
- Requiere Oracle 12c o superior.
- **Textos vacíos:** Oracle guarda `''` como NULL. El módulo lo resuelve igual que Django: en Oracle los textos opcionales admiten NULL y se leen como `''`, así que su código ve lo mismo que en cualquier otro motor. Si crea sus propias tablas, tenga en cuenta esta particularidad de Oracle.
- `oracledb` funciona en modo *thin* (Python puro) sin instalar nada más. El modo *thick* (Oracle Client) solo hace falta para funciones avanzadas como la autenticación por Kerberos o las billeteras antiguas.

Crear el usuario (como DBA):

```sql
CREATE USER app IDENTIFIED BY "…" QUOTA UNLIMITED ON USERS;
GRANT CREATE SESSION, CREATE TABLE, CREATE SEQUENCE TO app;
```

## SQL Server

```bash
pip install "fastapi-djauth[mssql]"        # instala pymssql: no necesita nada más del sistema
```

```python
AuthSettings(database={
    "ENGINE": "mssql",
    "NAME": "miapp",
    "USER": "app",
    "PASSWORD": os.environ["DB_PASSWORD"],
    "HOST": "sql.empresa.local",
    "PORT": 1433,
})
```

**Con pyodbc** (el controlador de Microsoft, necesario para Azure AD/Entra ID o funciones del controlador ODBC): instale el [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server) en el sistema y `pip install pyodbc`. Si `pyodbc` está instalado, se usa ese.

```python
AuthSettings(database={
    "ENGINE": "mssql", "NAME": "miapp", "USER": "app", "PASSWORD": os.environ["DB_PASSWORD"],
    "HOST": "sql.empresa.local", "PORT": 1433,
    "DRIVER": "pyodbc",
    "OPTIONS": {"driver": "ODBC Driver 18 for SQL Server", "Encrypt": "yes"},
})
```

- Con el ODBC Driver 18 la conexión va cifrada por defecto. Si el servidor usa un certificado propio (autofirmado), agregue `"TrustServerCertificate": "yes"` solo en redes de confianza.
- Requiere SQL Server 2016 o superior (o Azure SQL).

Crear la base y el usuario:

```sql
CREATE DATABASE miapp;
CREATE LOGIN app WITH PASSWORD = '…';
USE miapp;
CREATE USER app FOR LOGIN app;
ALTER ROLE db_owner ADD MEMBER app;
```

## Desde variables de entorno

Un patrón que sirve para cualquier motor (Docker, Kubernetes, servidores):

```python
import os

AuthSettings(database={
    "ENGINE": os.environ.get("DB_ENGINE", "sqlite"),
    "NAME": os.environ.get("DB_NAME", "./auth.sqlite3"),
    "USER": os.environ.get("DB_USER", ""),
    "PASSWORD": os.environ.get("DB_PASSWORD", ""),
    "HOST": os.environ.get("DB_HOST", ""),
    "PORT": os.environ.get("DB_PORT", ""),
})
```

O una sola variable con la URL: `AuthSettings(database_url=os.environ["DATABASE_URL"])`.

## Conexiones y rendimiento

- **Pool:** se usa el pool de SQLAlchemy (5 conexiones y hasta 10 extra por proceso). Cuente con eso al fijar el límite de conexiones del servidor: procesos × 15.
- **Conexiones cortadas:** cada conexión se verifica antes de usarse y se renueva cada `database_conn_max_age` segundos (por defecto 1800). Un reinicio de la base o un firewall que corta conexiones inactivas no produce errores.
- **Caché:** el usuario de cada sesión se guarda 5 segundos en memoria; la mayoría de las peticiones no consultan la base.

## Tablas que crea

Todas con el prefijo `table_prefix` (por defecto `auth_`): `user`, `group`, `permission`, `user_groups`, `user_user_permissions`, `group_permissions`, `session`, `log`, `user_history` y `meta`.

`kit.init()` las crea si no existen. Si después agrega columnas propias al usuario ([user_mixin](07-extender-usuario.md)), también las agrega a la tabla existente. No renombra ni borra columnas: para eso use una herramienta de migraciones como Alembic.

## Problemas frecuentes

| Error | Causa y solución |
|---|---|
| `database_config`: "No hay ningún controlador de … instalado" | Falta el controlador: instale el extra que indica la pista (`pip install "fastapi-djauth[postgres]"`…). |
| `database_config`: "El controlador … es asíncrono" | Use el controlador síncrono equivalente (ver arriba). |
| `database_config`: "Motor de base de datos no soportado" | `ENGINE` mal escrito. Válidos: `postgresql`, `mysql`, `sqlite`, `oracle`, `mssql` (y los nombres de Django). |
| `password authentication failed` / `Access denied for user` | Usuario o contraseña incorrectos, o el usuario no tiene permiso desde esa IP (MySQL: `'app'@'%'`). |
| `Connection refused` / `timeout` | Servidor apagado, puerto o host incorrectos, o un firewall en medio. Pruebe con el cliente del motor desde la misma máquina. |
| `unable to open database file` (SQLite) | La ruta no se puede escribir: revise permisos y, en Docker, el volumen. |
| `SSL` / `certificate verify failed` | Falta el certificado de la autoridad (`sslrootcert`, `ssl_ca`) o el nombre del servidor no coincide con el certificado. |
