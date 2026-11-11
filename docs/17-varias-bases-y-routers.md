# 17. Varias bases de datos y routers

Como `DATABASES` y `DATABASE_ROUTERS` en Django: un proyecto puede usar varias bases a la vez y decidir, modelo por modelo, en cuál se lee y en cuál se escribe. Sirve para:

- **Réplicas:** escribir en la primaria y leer de una o más réplicas.
- **Separar datos:** usuarios en una base, ventas en otra, sensores en una tercera, aunque sean motores distintos (PostgreSQL, MySQL, Oracle…).
- **Integrar sistemas existentes:** leer la base de otro sistema sin mezclarla con la suya.

Funciona para las tablas de djauth y también para los modelos de su aplicación.

## Configurar las bases

```python
import os
from djauth import AuthKit, AuthSettings

kit = AuthKit(AuthSettings(
    databases={
        "default": {                               # obligatoria, como en Django
            "ENGINE": "postgresql", "NAME": "miapp", "USER": "app",
            "PASSWORD": os.environ["DB_PASSWORD"], "HOST": "primaria.empresa.local",
        },
        "replica": {
            "ENGINE": "postgresql", "NAME": "miapp", "USER": "app_lectura",
            "PASSWORD": os.environ["DB_REPLICA_PASSWORD"], "HOST": "replica.empresa.local",
            "READ_ONLY": True,                     # nunca recibe escrituras ni tablas nuevas
        },
        "ventas": "mysql+pymysql://ventas:…@erp.empresa.local/ventas",   # también vale una URL
    },
    database_routers=["miapp.routers.PrimaryReplicaRouter"],
)).init()
```

Cada alias usa el mismo formato que `database` ([Bases de datos](15-bases-de-datos.md)) y acepta además:

| Clave | Por defecto | Para |
|---|---|---|
| `READ_ONLY` | `False` | Base de solo lectura (réplica): el módulo se niega a escribir o crear tablas en ella, aunque un router lo pida |
| `CONN_MAX_AGE` | `database_conn_max_age` (1800) | Segundos antes de renovar una conexión del pool |

`databases` tiene prioridad sobre `database` y `database_url`. Sin `databases`, todo funciona como siempre con una sola base.

## Escribir un router

Un router es una clase con cualquiera de estos cuatro métodos, los mismos de Django. Cada uno devuelve `None` cuando no tiene opinión, y entonces decide el siguiente router de la lista:

```python
# miapp/routers.py
import random


class PrimaryReplicaRouter:
    def db_for_read(self, model, **hints):
        return random.choice(["replica1", "replica2"])    # reparte las lecturas

    def db_for_write(self, model, **hints):
        return "default"                                  # todas las escrituras, a la primaria

    def allow_relation(self, obj1, obj2, **hints):
        return True                                       # primaria y réplicas tienen los mismos datos

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return db == "default"                            # las tablas se crean solo en la primaria
```

| Método | Devuelve | Si ningún router opina |
|---|---|---|
| `db_for_read(model, **hints)` | alias donde leer | `"default"` |
| `db_for_write(model, **hints)` | alias donde escribir | `"default"` |
| `allow_relation(obj1, obj2, **hints)` | `True` / `False` | solo si los dos se escriben en la misma base |
| `allow_migrate(db, app_label, model_name=None, **hints)` | `True` / `False` | se crean en `"default"`, no en las demás |

Cada modelo trae `model._meta.app_label`, `model._meta.model_name` y `model._meta.db_table`, como en Django.

- Los de djauth usan las mismas `app_label` que Django: `auth` (user, group, permission, userchange, meta), `sessions` (session) y `admin` (logentry). **Un router copiado de un proyecto Django funciona tal cual.**
- En sus modelos, declare `__app_label__ = "ventas"`. Si no lo declara, se deduce del módulo (`ventas.models.pedido` → `ventas`).

Los routers se indican como rutas (`"miapp.routers.PrimaryReplicaRouter"`), como clases o como instancias. Se consultan en orden.

## Ejemplo: usuarios en su propia base

El router `AuthRouter` de la documentación de Django, sin cambios:

```python
class AuthRouter:
    route_app_labels = {"auth", "contenttypes", "sessions", "admin"}

    def db_for_read(self, model, **hints):
        return "auth_db" if model._meta.app_label in self.route_app_labels else None

    def db_for_write(self, model, **hints):
        return "auth_db" if model._meta.app_label in self.route_app_labels else None

    def allow_relation(self, obj1, obj2, **hints):
        if obj1._meta.app_label in self.route_app_labels or obj2._meta.app_label in self.route_app_labels:
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in self.route_app_labels:
            return db == "auth_db"
        return None
```

Con `databases={"default": …, "auth_db": …}` y `database_routers=[AuthRouter]`, las tablas de usuarios se crean y usan solo en `auth_db`.

## Sus propios modelos en varias bases

`kit.databases` es el gestor de conexiones; úselo también para su aplicación. Si no usa djauth para eso, puede crear el suyo: `Databases(config, routers)`.

```python
from sqlalchemy import select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Pedido(Base):
    __tablename__ = "pedidos"
    __app_label__ = "ventas"
    id: Mapped[int] = mapped_column(primary_key=True)
    cliente: Mapped[str]


class VentasRouter:
    def db_for_read(self, model, **hints):
        return "ventas" if model._meta.app_label == "ventas" else None

    db_for_write = db_for_read

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return db == "ventas" if app_label == "ventas" else None


db = kit.databases
db.register(Base)          # da a conocer sus modelos al router
db.create_tables(Base)     # crea las tablas donde allow_migrate lo permite (o use Alembic)

with db.atomic() as session:                       # escribe; confirma al salir, deshace si hay error
    session.add(Pedido(cliente="Acme"))

with db.session() as session:                      # lee (puede ir a una réplica)
    pedidos = session.scalars(select(Pedido)).all()
```

En FastAPI, una sesión por petición:

```python
from collections.abc import Iterator

from djauth import RoutingSession


def get_session() -> Iterator[RoutingSession]:
    with kit.databases.session() as session:
        yield session
```

Una misma sesión puede tocar varias bases: cada consulta va a la que decide el router.

## Seguros

Son los de Django, más algunos que en Django quedan a cargo de quien programa:

| Seguro | Qué impide |
|---|---|
| **Las escrituras nunca van a una base `READ_ONLY`.** Si un router lo intenta, se lanza un error. | Corromper o desincronizar una réplica |
| **Leer, modificar y guardar ocurre en la misma base.** Una sesión de escritura (`atomic()` o `session(write=True)`) lee también de la base de escritura. | Guardar cambios sobre un dato viejo leído de una réplica atrasada (cambios perdidos) |
| **djauth valida contraseñas, sesiones y tokens siempre contra la base de escritura**, nunca contra una réplica. | Que una réplica atrasada acepte una contraseña ya cambiada o un token ya revocado. *En Django, esto depende de su router.* |
| **Las tablas de djauth se escriben todas en la misma base.** Si el router las reparte, la aplicación no arranca. | Que un cambio y su historial se guarden por separado, o relaciones usuario–grupo imposibles |
| **Claves foráneas entre bases distintas se rechazan al arrancar** (`check_relations`). | Relaciones rotas que Django solo detecta al usarlas |
| **`allow_relation` se comprueba antes de guardar.** Si un router dice `False`, se lanza un `ValueError`. | Mezclar objetos de bases que no deben relacionarse |
| **Un alias desconocido es un error** con la lista de alias válidos. | Escrituras a "ningún lado" por un error de tipeo |
| **Las tablas solo se crean donde `allow_migrate` lo permite**, y en las bases distintas de `default` solo si un router lo pide explícitamente. Nunca en `READ_ONLY`. | Tablas creadas en la base equivocada |
| **Las credenciales de cada alias se escapan** y nunca se muestran en logs ni errores. | Filtrar contraseñas |

**Transacciones:** como en Django, una transacción es por base. Si una misma sesión escribe en dos bases, cada una confirma por su lado: no hay un "todo o nada" entre bases distintas. Mantenga juntas, en la misma base, las tablas que deben guardarse juntas. djauth ya lo hace con las suyas.

**Réplicas atrasadas:** una lectura desde una réplica puede no ver lo que se acaba de escribir en la primaria. Para leer algo recién guardado, use una sesión de escritura (`session(write=True)`).

## Desde Django

| Django | djauth |
|---|---|
| `DATABASES = {...}` | `AuthSettings(databases={...})` |
| `DATABASE_ROUTERS = ["miapp.routers.X"]` | `AuthSettings(database_routers=["miapp.routers.X"])` |
| `"TEST": {"MIRROR": "default"}` (réplica) | `"READ_ONLY": True` |
| `CONN_MAX_AGE` por alias | `CONN_MAX_AGE` por alias |
| `Model.objects.using("x")` | `kit.databases.engine("x")` o una sesión de SQLAlchemy sobre ese motor |
| `transaction.atomic()` | `kit.databases.atomic()` |
| `migrate --database x` | `kit.databases.create_tables(Base, aliases=["x"])`, o Alembic |
| `model._meta.app_label` | `model._meta.app_label` (en sus modelos, `__app_label__`) |
