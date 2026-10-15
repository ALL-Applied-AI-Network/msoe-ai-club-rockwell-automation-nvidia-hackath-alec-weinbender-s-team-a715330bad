"""SQLite persistence. Everything the LLM proposes and everything the optimizer
tries/chooses is stored here, so it doubles as the training set for the
stretch-goal 'bad suggestion' filter."""
import json, os, sqlite3, time
from pathlib import Path

DATA = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DATA.mkdir(parents=True, exist_ok=True)
(DATA / "uploads").mkdir(exist_ok=True)
(DATA / "outputs").mkdir(exist_ok=True)
DB_PATH = DATA / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY, created REAL, status TEXT, part_name TEXT, part_path TEXT,
  part TEXT, task TEXT, config TEXT, n_done INTEGER DEFAULT 0, n_total INTEGER DEFAULT 0,
  stage TEXT, best_value REAL, best_trial INTEGER, error TEXT,
  cancel_requested INTEGER DEFAULT 0, pid INTEGER, finished REAL);
CREATE TABLE IF NOT EXISTS suggestions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, idx INTEGER, template TEXT, params TEXT,
  rationale TEXT, source TEXT, model TEXT, raw_response TEXT, created REAL, trial_number INTEGER);
CREATE TABLE IF NOT EXISTS trials(
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, number INTEGER, template TEXT, params TEXT,
  success_rate REAL, n_grasps INTEGER, n_success INTEGER, pruned INTEGER, suggestion_id INTEGER,
  duration REAL, created REAL, UNIQUE(job_id, number));
CREATE TABLE IF NOT EXISTS results(
  job_id TEXT PRIMARY KEY, trial_number INTEGER, template TEXT, params TEXT, grasp_pose TEXT,
  predicted_success REAL, ci_low REAL, ci_high REAL, scad_path TEXT, created REAL);
CREATE TABLE IF NOT EXISTS run_meta(job_id TEXT PRIMARY KEY, meta TEXT);
CREATE TABLE IF NOT EXISTS reviews(job_id TEXT PRIMARY KEY, status TEXT, reviewer TEXT, notes TEXT, created REAL);
CREATE TABLE IF NOT EXISTS physical_trials(
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, created REAL, finger TEXT, success INTEGER,
  placement_error_mm REAL, cycle_time_s REAL, recovered INTEGER, operator_intervention INTEGER, notes TEXT);
"""

def conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c

def init():
    with conn() as c:
        c.executescript(SCHEMA)

def run(sql, args=()):
    with conn() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid

def rows(sql, args=()):
    with conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]

def row(sql, args=()):
    r = rows(sql, args)
    return r[0] if r else None

JSON_COLS = ("part", "config", "params", "grasp_pose", "meta")
def decode(d):
    if d is None: return None
    for k in JSON_COLS:
        if k in d and isinstance(d[k], str):
            d[k] = json.loads(d[k])
    return d

def update_job(job_id, **kw):
    cols = ", ".join(f"{k}=?" for k in kw)
    run(f"UPDATE jobs SET {cols} WHERE id=?", (*kw.values(), job_id))

def now(): return time.time()
