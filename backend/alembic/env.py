"""Alembic environment.

Two deliberate choices:

- The URL is set here, from Settings, rather than in alembic.ini. One source of truth for where
  the database is; `alembic.ini` has its `sqlalchemy.url` commented out.
- `render_as_batch=True`. SQLite cannot ALTER most things in place, so Alembic has to rebuild
  the table. Without this, any future migration that drops a column or changes a constraint
  fails at upgrade time rather than at autogenerate time - which is to say, on someone else's
  machine.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from expense_api.config.settings import settings
from expense_api.db.models import Base

config = context.config

# SQLite will not create a missing parent directory, and Alembic is usually the first thing to
# touch the database on a fresh clone - before the app has imported db/database.py, which does
# this for the runtime path.
settings.database_path.parent.mkdir(parents=True, exist_ok=True)

config.set_main_option("sqlalchemy.url", settings.sync_database_url)

if config.config_file_name is not None:
    # disable_existing_loggers=False: the default silently kills pytest's caplog for the rest
    # of the session, which makes any later logging assertion mysteriously fail.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def render_item(type_: str, obj: object, autogen_context: object) -> str | bool:
    """Render the custom `Money` type as the integer column it actually is.

    Autogenerate would otherwise emit `expense_api.db.types.Money()` without importing it, so
    the migration fails with NameError on upgrade. Rendering `sa.Integer()` instead fixes that
    and is the better dependency direction anyway: a migration that imports application code
    stops working the day that code is moved, and a migration has to keep running forever.

    Money is an integer count of paise at the storage level, so no DDL fidelity is lost.
    """
    if type_ == "type" and type(obj).__name__ == "Money":
        return "sa.Integer()"
    # Everything else falls through to Alembic's default rendering.
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        render_item=render_item,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            render_item=render_item,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
