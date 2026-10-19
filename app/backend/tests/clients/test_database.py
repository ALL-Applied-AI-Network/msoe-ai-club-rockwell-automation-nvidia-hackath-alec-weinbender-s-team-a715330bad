import json
import sqlite3

from api.clients.database import BASELINE_REVISION, DatabaseClient
from api.config import AppConfig
from api.models.job import JobConfig
from api.models.part import Part
from api.services import jobs

# The schema the app created before Alembic, as found in teammates' existing app.db files.
PRE_ALEMBIC_SCHEMA = """
CREATE TABLE jobs(
  id TEXT PRIMARY KEY, created REAL, status TEXT, part_name TEXT, part_path TEXT,
  part TEXT, task TEXT, config TEXT, n_done INTEGER DEFAULT 0, n_total INTEGER DEFAULT 0,
  stage TEXT, best_value REAL, best_trial INTEGER, error TEXT,
  cancel_requested INTEGER DEFAULT 0, pid INTEGER, finished REAL);
CREATE TABLE suggestions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, idx INTEGER, template TEXT, params TEXT,
  rationale TEXT, source TEXT, model TEXT, raw_response TEXT, created REAL, trial_number INTEGER);
CREATE TABLE trials(
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, number INTEGER, template TEXT, params TEXT,
  success_rate REAL, n_grasps INTEGER, n_success INTEGER, pruned INTEGER, suggestion_id INTEGER,
  duration REAL, created REAL, UNIQUE(job_id, number));
CREATE TABLE results(
  job_id TEXT PRIMARY KEY, trial_number INTEGER, template TEXT, params TEXT, grasp_pose TEXT,
  predicted_success REAL, ci_low REAL, ci_high REAL, scad_path TEXT, created REAL);
CREATE TABLE run_meta(job_id TEXT PRIMARY KEY, meta TEXT);
CREATE TABLE reviews(job_id TEXT PRIMARY KEY, status TEXT, reviewer TEXT, notes TEXT, created REAL);
CREATE TABLE physical_trials(
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, created REAL, finger TEXT, success INTEGER,
  placement_error_mm REAL, cycle_time_s REAL, recovered INTEGER, operator_intervention INTEGER, notes TEXT);
"""


def test_database_from_before_migrations_is_stamped_and_keeps_its_data(tmp_path):
    old = sqlite3.connect(tmp_path / "app.db")
    old.executescript(PRE_ALEMBIC_SCHEMA)
    old.execute(
        "INSERT INTO jobs(id,created,status,part_name,part,task,config,n_total) VALUES(?,?,?,?,?,?,?,?)",
        ("old1", 1.0, "done", "manual", json.dumps(Part(diameter_mm=12).model_dump()), "pick", json.dumps(JobConfig().model_dump()), 60),
    )
    old.commit()
    old.close()
    db = DatabaseClient(AppConfig(data_dir=tmp_path).db)

    db.migrate()

    with db.engine.connect() as connection:
        version = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
    job = jobs.get_job(db, "old1")
    db.close()
    assert version == BASELINE_REVISION
    assert (job.part, job.config) == (Part(diameter_mm=12), JobConfig())


def test_migrating_an_up_to_date_database_changes_nothing(db):
    db.migrate()

    with db.engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM alembic_version").scalar() == 1
