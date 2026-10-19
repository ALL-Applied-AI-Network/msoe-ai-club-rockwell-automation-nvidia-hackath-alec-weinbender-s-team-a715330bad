"""The database connection: an engine and sessions built from DbConfig. SQLite today (one file in DATA_DIR); Postgres
by changing DB_URL. What's stored (tables, migrations) lives in api/db.

There's one implementation, not a mock and a real one: tests use a temporary SQLite file.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from api.config import DbConfig

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "db" / "migrations"
BASELINE_REVISION = "0001"  # the schema as it was before Alembic


class DatabaseClient:
    def __init__(self, config: DbConfig):
        self.url = make_url(config.url.get_secret_value())
        self.is_sqlite = self.url.get_backend_name() == "sqlite"
        options = {"echo": config.echo, "pool_pre_ping": True}
        if self.is_sqlite:
            Path(self.url.database).parent.mkdir(parents=True, exist_ok=True)
            # The API's threads and the detached workers all share the file; wait for locks instead of failing.
            options["connect_args"] = {"timeout": 30, "check_same_thread": False}
        self.engine = create_engine(self.url, **options)
        if self.is_sqlite:
            event.listen(self.engine, "connect", _use_wal)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)
        logger.info("Database: %s", self.url.database if self.is_sqlite else self.url.render_as_string(hide_password=True))

    @contextmanager
    def session(self) -> Iterator[Session]:
        """One unit of work: commits when the block ends, rolls back if it raises. Keep it short, so other processes
        see the changes (the UI watches job progress live)."""
        with self._sessions.begin() as session:
            yield session

    def migrate(self) -> None:
        """Upgrade the schema to the latest migration. A database created before Alembic is stamped as the baseline
        first, so its data is kept."""
        alembic_config = AlembicConfig()
        alembic_config.set_main_option("script_location", str(MIGRATIONS_DIR))
        with self.engine.begin() as connection:
            alembic_config.attributes["connection"] = connection
            tables = set(inspect(connection).get_table_names())
            if "jobs" in tables and "alembic_version" not in tables:
                logger.warning("Database: predates migrations; stamping it as revision %s", BASELINE_REVISION)
                command.stamp(alembic_config, BASELINE_REVISION)
            command.upgrade(alembic_config, "head")

    def close(self) -> None:
        self.engine.dispose()


def create_database_client(config: DbConfig) -> DatabaseClient:
    return DatabaseClient(config)


def _use_wal(dbapi_connection, connection_record) -> None:
    dbapi_connection.execute("PRAGMA journal_mode=WAL")
