# Migraciones de las tablas de la aplicación. La URL de la base se toma de APP_DATABASE_URL (.env).
#   uv run alembic revision --autogenerate -m "describa el cambio"
#   uv run alembic upgrade head
[alembic]
script_location = %(here)s/migrations
prepend_sys_path = src
file_template = %%(year)d%%(month).2d%%(day).2d_%%(rev)s_%%(slug)s

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
