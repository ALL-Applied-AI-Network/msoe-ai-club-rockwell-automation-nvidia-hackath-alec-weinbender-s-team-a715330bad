"""The detached process that runs one job, started by the API:  python -m api.worker <job_id>

It outlives API reloads. Its clients live exactly as long as the job: created from the config here, passed to the
optimizer, closed when it returns. The API has already migrated the database.
"""

import sys
from contextlib import closing

from api.clients.cad import create_cad_client
from api.clients.database import create_database_client
from api.clients.llm import create_llm_client
from api.clients.sim import create_sim_client
from api.config import load_config, setup_logging
from api.services.optimizer import run_job


def main(job_id: str) -> None:
    setup_logging()
    config = load_config()
    setup_logging(config.log_level)
    with (
        closing(create_database_client(config.db)) as db,
        closing(create_llm_client(config.llm)) as llm,
        closing(create_sim_client(config.sim)) as sim,
        closing(create_cad_client()) as cad,
    ):
        run_job(db, job_id, llm=llm, sim=sim, cad=cad, outputs_dir=config.outputs_dir)


if __name__ == "__main__":
    main(sys.argv[1])
