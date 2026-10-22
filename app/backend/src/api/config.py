"""Settings, secrets and logging setup. The only module that reads environment variables.

Each client has its own config section, filled from its prefixed variables (LLM_*, SIM_*, DB_*), and AppConfig combines them
with the app-wide settings. Real environment variables win over the repo-root .env. Every variable is listed in
.env.example.
"""

import logging
import shlex
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Literal, NoReturn
from urllib.parse import urlparse

from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from api.models.compute import COMPUTE_BACKENDS, ComputeBackend

APP_DIR = Path(__file__).resolve().parents[3]  # app/  (this file is app/backend/src/api/config.py)
ENV_FILE = APP_DIR.parent / ".env"
LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DEMO_DIR_NAME = "demo"  # DEMO_DATA=true runs in DATA_DIR/demo
DEMO_SCRIPT = APP_DIR / "backend" / "scripts" / "demo_data.py"
CAD_DIR = APP_DIR.parent / "cad"  # the organizers' CAD of the cell: the lab parts load from here

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
    # A round whose connection drops (the VPN, the GPU's port forward) waits this long for the sim to answer again, then
    # fails (the job can be resumed). 0: fail at once.
    reconnect_minutes: float = Field(120, ge=0)
    grasps_per_s: float | None = Field(None, gt=0)  # throughput for time estimates until runs on this backend have measured it


class ComputeConfig(BaseModel):
    """COMPUTE_* variables: the GPU targets the app connects the sim to. Brev instances are started for the sim and
    stopped when idle; the MSOE GB10 is always on and shared, so the app only connects to it."""

    # The enabled targets, comma-separated: mock (made-up instances, the default), brev, gb10. One is connected at a time.
    backends: str = "mock"
    auto_stop_minutes: float = Field(20, ge=0)  # Brev: stop the instance after this long without a job; 0: never
    start_timeout_s: float = Field(1200, gt=0)  # boot, the container and Isaac Sim's start, together
    # Brev
    brev_cli: str = "brev"  # the Brev CLI's command or path (inside WSL when brev_wsl is set)
    # Windows: the WSL distro the CLI is installed in (e.g. Ubuntu), since it only runs there. The app then runs it
    # through a login shell in that distro, so ~/.local/bin is on PATH and every argument arrives exactly as sent.
    brev_wsl: str | None = None
    brev_token: SecretStr | None = None  # logs the CLI in when the app starts (brev login --token); unset: its own login
    sim_port: int = Field(9000, gt=0, lt=65536)  # where the sim server listens on the instance (the forward's far end)
    sim_container: str = "vscode"  # the Docker container Isaac Sim runs in (the Isaac launchable's); "" for none
    sim_dir: str = "/root/repo"  # the repo on the instance (inside that container)
    isaac_python: str = "/isaac-sim/python.sh"
    sim_args: str = ""  # extra sim_server flags, e.g. "--envs 64"
    # MSOE GB10, over SSH (on the MSOE VPN, with your key on the team account: no password setting, by team rule)
    ssh: str = "ssh"  # the ssh command; on Windows the built-in OpenSSH
    gb10_host: str = "spark1.ai.msoe.edu"
    gb10_user: str = "hackathon11"
    gb10_sim_port: int = Field(9011, gt=0, lt=65536)  # not 9000: other accounts can reach the GB10's localhost ports
    gb10_sim_dir: str = "/home/hackathon11/repo"
    gb10_isaac_python: str = "/home/hackathon11/isaac-sim-6.0.1/python.sh"
    gb10_sim_args: str = ""

    @field_validator("backends")
    @classmethod
    def _known_backends(cls, value: str) -> str:
        names = list(dict.fromkeys(name.strip().lower() for name in value.split(",") if name.strip()))
        unknown = [name for name in names if name not in COMPUTE_BACKENDS]
        if not names or unknown:
            raise ValueError(f"list the targets from {', '.join(COMPUTE_BACKENDS)}, comma-separated (got {value!r})")
        return ",".join(names)

    @property
    def enabled(self) -> list[ComputeBackend]:
        return self.backends.split(",")  # type: ignore[return-value]  # validated above


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
    compute: ComputeConfig = Field(default_factory=ComputeConfig)
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

    @property
    def compute_log(self) -> Path:
        return self.data_dir / "compute.log"


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
    compute_errors, compute_warnings = _check_compute(config.compute, sim)
    errors += compute_errors
    warnings += compute_warnings
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


def _check_compute(compute: ComputeConfig, sim: SimConfig) -> tuple[list[str], list[str]]:
    """Every real target forwards its sim server to SIM_URL's port on this machine, so it needs the http sim at a local
    address, and the tool that reaches it (the Brev CLI, ssh)."""
    real = [name for name in compute.enabled if name != "mock"]
    if not real:
        return [], ["Compute: using the mock (made-up instances). Set COMPUTE_BACKENDS=brev,gb10 to connect a real GPU from the app."]
    errors, warnings = [], []
    host = urlparse(sim.url or "").hostname
    if sim.backend != "http" or host not in ("localhost", "127.0.0.1"):
        errors.append(
            f"COMPUTE_BACKENDS={compute.backends} forwards the sim server to this machine, so it needs SIM_BACKEND=http and a "
            "local SIM_URL, e.g. http://127.0.0.1:9000."
        )
    if "gb10" in real and shutil.which(shlex.split(compute.ssh or "ssh")[0]) is None:
        errors.append(f"COMPUTE_SSH: can't find {compute.ssh!r}, which the GB10 is reached with. Install OpenSSH (SETUP.md).")
    if "brev" in real:
        if compute.brev_wsl and shutil.which("wsl") is None:
            errors.append("COMPUTE_BREV_WSL is set, but there's no wsl command here: it's for Windows with WSL (SETUP.md).")
        elif not compute.brev_wsl and shutil.which(shlex.split(compute.brev_cli or "brev")[0]) is None:
            errors.append(
                f"COMPUTE_BREV_CLI: can't find {compute.brev_cli!r}. Install the Brev CLI (SETUP.md). On Windows it runs in "
                "WSL: set COMPUTE_BREV_WSL=Ubuntu (the distro it's installed in)."
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
    logger.info(
        "Config: llm=%s, sim=%s, compute=%s, data_dir=%s", config.llm.backend, config.sim.backend, config.compute.backends, config.data_dir
    )
    return config


def _fail(errors: list[str]) -> NoReturn:
    for message in errors:
        logger.error("Config: %s", message)
    raise ConfigError(f"{len(errors)} config problem(s), listed above. Set them in {ENV_FILE} (template: .env.example).")


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger. Entrypoints call this first, then again with config.log_level once it's loaded."""
    logging.basicConfig(level=level, format=LOG_FORMAT, force=True)
