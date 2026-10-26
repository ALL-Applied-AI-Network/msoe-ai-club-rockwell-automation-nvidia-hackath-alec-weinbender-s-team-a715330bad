"""The detached process that does a job's sim work, started by the API (services/jobs.py: spawn_worker):

    python -m api.worker <job_id>                     run (or resume) the job: a generation job's search, final test
                                                      and D1's CAD, or an evaluation job's fingers (services/evaluator.py)
    python -m api.worker <job_id> predict <plan_id>   predict every trial of one of the job's physical test plans
    python -m api.worker <job_id> clip <clip_id>      film one of the job's clips in Isaac Sim

It outlives API reloads. Its clients (sim, CAD, database) live exactly as long as the task: created from the config here,
passed to the service, closed when it returns. The API has already migrated the database.
"""

import logging
import sys
from contextlib import closing

from api.clients.cad import create_cad_client
from api.clients.database import create_database_client
from api.clients.sim import create_sim_client
from api.config import load_config, setup_logging
from api.services import clips, test_plans
from api.services.optimizer import run_job

logger = logging.getLogger(__name__)

USAGE = "usage: python -m api.worker <job_id> [predict <plan_id> | clip <clip_id>]"


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    task = _task(args)
    setup_logging()
    config = load_config()
    setup_logging(config.log_level)
    job_id = args[0]
    with (
        closing(create_database_client(config.db)) as db,
        closing(create_sim_client(config.sim)) as sim,
        closing(create_cad_client()) as cad,
    ):
        if task is None:
            run_job(db, job_id, sim=sim, cad=cad, outputs_dir=config.outputs_dir)
        elif task[0] == "predict":
            logger.info("Job %s: predicting test plan %d", job_id, task[1])
            test_plans.predict_test_plan(db, task[1], sim=sim)
        else:
            logger.info("Job %s: recording clip %d", job_id, task[1])
            clips.record_clip(db, task[1], sim=sim, outputs_dir=config.outputs_dir)


def _task(args: list[str]) -> tuple[str, int] | None:
    """("predict", plan id) or ("clip", clip id), or None to run the job; exits with the usage line for anything else."""
    if len(args) == 1:
        return None
    if len(args) == 3 and args[1] in ("predict", "clip") and args[2].isdigit():
        return args[1], int(args[2])
    raise SystemExit(USAGE)


if __name__ == "__main__":
    main()
