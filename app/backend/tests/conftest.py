import os
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from api.clients.cad import OpenScadCad
from api.clients.database import DatabaseClient
from api.clients.sim import MockSim
from api.config import AppConfig
from api.dependencies import get_config, get_db
from api.main import app
from api.models.job import JobConfig
from api.models.part import Part
from api.services import jobs
from api.services.optimizer import run_job

APP_VARIABLES = ("ANTHROPIC_API_KEY", "DATA_DIR", "LOG_LEVEL")
SMALL_JOB = JobConfig(budget=6, batch_size=3)  # two rounds: the baselines + 3 Sobol designs, then 3 from the GP


@pytest.fixture(autouse=True, scope="session")
def _isolated_from_developer_settings():
    """Tests never read the developer's .env or exported app variables."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(AppConfig.model_config, "env_file", None)
        for name in list(os.environ):
            if name.startswith(("LLM_", "SIM_")) or name in APP_VARIABLES:
                mp.delenv(name)
        yield


@pytest.fixture
def config(tmp_path) -> AppConfig:
    """Mock backends (the defaults) and a temporary data directory."""
    return AppConfig(data_dir=tmp_path)


@pytest.fixture
def db(config) -> DatabaseClient:
    """A fresh SQLite file in the temporary data directory, built by running the real migrations."""
    database = DatabaseClient(config.db)
    database.migrate()
    yield database
    database.close()


@pytest.fixture
def spawned(monkeypatch) -> list[str]:
    """Stops services from launching real worker processes. Records the job ids instead."""
    started = []
    monkeypatch.setattr(jobs, "spawn_worker", lambda db, config, job_id: started.append(job_id))
    return started


@pytest.fixture
def client(config, db, spawned):
    """The API over the temporary database. The lifespan doesn't run, so nothing reads the real config."""
    app.dependency_overrides = {get_config: lambda: config, get_db: lambda: db}
    yield TestClient(app)
    app.dependency_overrides = {}


@dataclass
class FinishedJob:
    config: AppConfig
    db: DatabaseClient
    job_id: str


@pytest.fixture(scope="session")
def finished_job(tmp_path_factory) -> FinishedJob:
    """A small job run to completion with the mock clients, shared by read-only tests. Fits a real GP, so it takes a few
    seconds."""
    config = AppConfig(data_dir=tmp_path_factory.mktemp("finished"))
    db = DatabaseClient(config.db)
    db.migrate()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(jobs, "spawn_worker", lambda *args: None)
        job_id = jobs.create_job(db, config, task="pick and sort", part=Part(), job_config=SMALL_JOB)
    run_job(db, job_id, sim=MockSim(), cad=OpenScadCad(), outputs_dir=config.outputs_dir)
    yield FinishedJob(config, db, job_id)
    db.close()


@pytest.fixture
def finished_client(finished_job):
    """The API over the finished job's database. Read-only use only: the database is shared across tests."""
    app.dependency_overrides = {get_config: lambda: finished_job.config, get_db: lambda: finished_job.db}
    yield TestClient(app)
    app.dependency_overrides = {}
