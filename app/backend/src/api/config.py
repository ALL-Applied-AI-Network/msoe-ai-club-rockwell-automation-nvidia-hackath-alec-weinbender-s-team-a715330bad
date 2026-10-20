"""Settings, secrets and logging setup. The only module that reads environment variables.

Each client has its own config section, filled from its prefixed variables (LLM_*, SIM_*, DB_*), and AppConfig combines them
with the app-wide settings. Real environment variables win over the repo-root .env. Every variable is listed in
.env.example.
"""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal, NoReturn

from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

APP_DIR = Path(__file__).resolve().parents[3]  # app/  (this file is app/backend/src/api/config.py)
ENV_FILE = APP_DIR.parent / ".env"
LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DEMO_DIR_NAME = "demo"  # DEMO_DATA=true runs in DATA_DIR/demo
DEMO_SCRIPT = APP_DIR / "backend" / "scripts" / "demo_data.py"

logger = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    """The configuration can't be used. Every problem has already been logged."""


class LlmConfig(BaseModel):
    """LLM_* variables. The key is read from ANTHROPIC_API_KEY, its standard name."""

    backend: Literal["mock", "anthropic", "http"] | None = None  # unset: anthropic if a key is set, else mock
    model: str = "claude-sonnet-5-5"
    url: str | None = None  # http backend: POST {part, task, k} -> {suggestions: [...]}
    api_key: SecretStr | None = None


class SimConfig(BaseModel):
    """SIM_* variables."""

    backend: Literal["mock", "http"] = "mock"
    url: str | None = None  # http backend: the sim server's base URL; the client posts to {url}/evaluate_batch
    timeout_s: float = 3600  # one request is a whole round (designs x grid points), which can take a while
    grasps_per_s: float | None = Field(None, gt=0)  # throughput for time estimates until runs on this backend have measured it


class DbConfig(BaseModel):
    """DB_* variables."""

    url: SecretStr | None = None  # SQLAlchemy URL, e.g. postgresql+psycopg://... unset: SQLite file in DATA_DIR
    echo: bool = False  # log every SQL statement
    auto_migrate: bool = True  # API startup runs `alembic upgrade head`; turn off where deploys run migrations


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_nested_delimiter="_",
        env_nested_max_split=1,  # LLM_API_KEY -> llm.api_key, not llm.api.key
        extra="ignore",  # the shared .env also holds the twin's variables
    )

    data_dir: Path = APP_DIR / "data"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    anthropic_api_key: SecretStr | None = None
    # Run on generated demo data (app/backend/scripts/demo_data.py) in DATA_DIR/demo, with its own SQLite file, never the
    # real database. The API generates it in the background on the first start.
    demo_data: bool = False

    llm: LlmConfig = Field(default_factory=LlmConfig)
    sim: SimConfig = Field(default_factory=SimConfig)
    db: DbConfig = Field(default_factory=DbConfig)

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _resolve_defaults(self) -> "AppConfig":
        if self.llm.api_key is None:
            self.llm.api_key = self.anthropic_api_key
        if self.llm.backend is None:
            self.llm.backend = "anthropic" if self.llm.api_key else "mock"
        if self.demo_data:
            if self.db.url is not None:
                raise ValueError("DEMO_DATA=true keeps the demo in its own SQLite file under DATA_DIR/demo; unset DB_URL")
            if self.data_dir.name != DEMO_DIR_NAME:
                self.data_dir = self.data_dir / DEMO_DIR_NAME
        if self.db.url is None:
            self.db.url = SecretStr(f"sqlite:///{(self.data_dir / 'app.db').as_posix()}")
        return self

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def outputs_dir(self) -> Path:
        return self.data_dir / "outputs"

    @property
    def worker_log(self) -> Path:
        return self.data_dir / "worker.log"


def check_config(config: AppConfig) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors are settings a selected backend can't run without."""
    errors, warnings = [], []
    llm, sim = config.llm, config.sim
    if llm.backend == "mock":
        warnings.append(
            "LLM: using the mock (the optimizer doesn't call the LLM at the moment). "
            "Set ANTHROPIC_API_KEY (or LLM_BACKEND=http and LLM_URL) for real suggestions."
        )
    elif llm.backend == "anthropic" and llm.api_key is None:
        errors.append("LLM_BACKEND=anthropic needs ANTHROPIC_API_KEY, the Claude API key.")
    elif llm.backend == "http" and not llm.url:
        errors.append("LLM_BACKEND=http needs LLM_URL, the suggestion service's endpoint.")
    if sim.backend == "mock":
        warnings.append("Sim: using the mock simulator, whose success rates are made up. Set SIM_BACKEND=http and SIM_URL for the twin.")
    elif not sim.url:
        errors.append("SIM_BACKEND=http needs SIM_URL, the sim server's base URL (e.g. http://localhost:9000).")
    try:
        make_url(config.db.url.get_secret_value())
    except ArgumentError:
        errors.append("DB_URL isn't a valid SQLAlchemy URL (e.g. postgresql+psycopg://user:password@host/dbname).")
    if config.demo_data:
        warnings.append(
            f"Demo data: running on generated demo data in {config.data_dir} (mock results, made-up physical trials), "
            "not the real database. Unset DEMO_DATA for real work."
        )
    return errors, warnings


@lru_cache
def load_config() -> AppConfig:
    """Load and check the config once per process. Logs every problem at once, then raises ConfigError."""
    try:
        config = AppConfig()
    except ValidationError as e:
        _fail([f"{'_'.join(map(str, err['loc'])).upper()}: {err['msg']}" for err in e.errors()])
    errors, warnings = check_config(config)
    for message in warnings:
        logger.warning("Config: %s", message)
    if errors:
        _fail(errors)
    logger.info("Config: llm=%s, sim=%s, data_dir=%s", config.llm.backend, config.sim.backend, config.data_dir)
    return config


def _fail(errors: list[str]) -> NoReturn:
    for message in errors:
        logger.error("Config: %s", message)
    raise ConfigError(f"{len(errors)} config problem(s), listed above. Set them in {ENV_FILE} (template: .env.example).")


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger. Entrypoints call this first, then again with config.log_level once it's loaded."""
    logging.basicConfig(level=level, format=LOG_FORMAT, force=True)
