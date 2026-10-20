"""The Finger Designer API and the static UI.

    uv run --package backend uvicorn api.main:app --port 8000

LLM and sim calls don't happen here: each job (and each test-plan prediction) runs in its own detached worker process
(see worker.py). The API uses the CAD client directly, for uploaded parts and finger downloads.
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.clients.cad import create_cad_client
from api.clients.database import DatabaseClient, create_database_client
from api.config import APP_DIR, DEMO_SCRIPT, AppConfig, load_config, setup_logging
from api.routers import (
    cell_profiles,
    export,
    fingers,
    grids,
    health,
    jobs,
    meta,
    parts,
    physical_trials,
    printed_fingers,
    test_plans,
)
from api.services.cell_profiles import ensure_default_profile
from api.services.jobs import mark_interrupted, spawn_detached
from api.services.parts import list_parts

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: logging, then the config check (startup stops on errors), then the database, its migrations and the
    default cell profile. Long-lived resources the API itself needs are created here, stored on app.state for
    dependencies.py, and closed after the yield."""
    setup_logging()
    config = load_config()
    setup_logging(config.log_level)
    db = create_database_client(config.db)
    if config.db.auto_migrate:
        db.migrate()
    ensure_default_profile(db)
    mark_interrupted(db)
    if config.demo_data:
        start_demo_data(db, config)
    app.state.config, app.state.db, app.state.cad = config, db, create_cad_client()
    logger.info("API ready")
    yield
    app.state.cad.close()
    db.close()


def start_demo_data(db: DatabaseClient, config: AppConfig) -> None:
    """DEMO_DATA=true: on the first start (no parts yet), generate the demo data (scripts/demo_data.py) in a detached
    process, so the API answers at once and the experiments appear as they finish, in about two minutes."""
    if list_parts(db):
        return
    log = config.data_dir / "demo_data.log"
    pid = spawn_detached([sys.executable, str(DEMO_SCRIPT), "--data-dir", str(config.data_dir)], log)
    logger.warning("Demo data: generating it in the background (pid %s, log %s); experiments appear as they finish", pid, log)


app = FastAPI(title="Finger Designer", lifespan=lifespan)
for module in (health, meta, parts, cell_profiles, fingers, grids, jobs, test_plans, printed_fingers, physical_trials, export):
    app.include_router(module.router)
app.mount("/", StaticFiles(directory=APP_DIR / "frontend", html=True), name="static")  # last: it matches every path
