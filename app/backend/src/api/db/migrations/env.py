"""Alembic environment. The CLI connects through the app's DatabaseClient and config (DB_URL, or the SQLite file in
DATA_DIR), never through alembic.ini, so the CLI and the app always reach the same database the same way."""

from logging.config import fileConfig

from alembic import context

from api.clients.database import DatabaseClient
from api.config import AppConfig
from api.db.tables import Base, PydanticJSON

config = context.config


def render_item(type_, obj, autogen_context):
    """Write typed JSON columns as plain JSON in migrations, so migrations don't import the models."""
    if type_ == "type" and isinstance(obj, PydanticJSON):
        return "sa.JSON()"
    return False


def run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_as_batch=True,  # SQLite can't ALTER most columns; batch mode rebuilds the table instead
        compare_type=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) migrations aren't set up; run them against a database.")

connection = config.attributes.get("connection")  # passed in by DatabaseClient.migrate()
if connection is not None:
    run_migrations(connection)
else:  # the alembic CLI
    if config.config_file_name:
        fileConfig(config.config_file_name)
    database = DatabaseClient(AppConfig().db)
    with database.engine.connect() as connection:
        run_migrations(connection)
        connection.commit()
    database.close()
