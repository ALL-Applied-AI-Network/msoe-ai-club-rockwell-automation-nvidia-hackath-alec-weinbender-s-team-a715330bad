"""The Finger Designer API and the static UI.

    uv run --package backend uvicorn api.main:app --port 8000

LLM, sim and CAD calls don't happen here: each job runs in its own detached worker process (see worker.py).
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.clients.database import create_database_client
from api.config import APP_DIR, load_config, setup_logging
from api.routers import export, health, jobs, meta
from api.services.jobs import mark_interrupted

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: logging, then the config check (startup stops on errors), then the database and its migrations.
    Long-lived resources the API itself needs are created here, stored on app.state for dependencies.py, and closed
    after the yield."""
    setup_logging()
    config = load_config()
    setup_logging(config.log_level)
    db = create_database_client(config.db)
    if config.db.auto_migrate:
        db.migrate()
    mark_interrupted(db)
    app.state.config, app.state.db = config, db
    logger.info("API ready")
    yield
    db.close()


app = FastAPI(title="Finger Designer", lifespan=lifespan)
for module in (health, meta, jobs, export):
    app.include_router(module.router)
app.mount("/", StaticFiles(directory=APP_DIR / "frontend", html=True), name="static")  # last: it matches every path
