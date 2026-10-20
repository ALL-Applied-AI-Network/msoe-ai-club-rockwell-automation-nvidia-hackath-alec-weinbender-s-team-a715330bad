"""The detached process that runs one GPU session, started by the API (services/compute.py: spawn_session):

    python -m api.compute_worker <session_id>

It brings the session's target up for the sim server (a Brev instance it starts, or the always-on GB10), holds the port
forward the job workers' sim requests go through, and ends the session when asked (or, on Brev, after
COMPUTE_AUTO_STOP_MINUTES without a job), then exits. Like the job workers it outlives API reloads. Its compute client is
built from the session's backend, and its clients live exactly as long as the session.
"""

import logging
import sys
from contextlib import closing

from api.clients.compute import create_compute_client
from api.clients.database import create_database_client
from api.clients.sim import create_sim_client
from api.config import load_config, setup_logging
from api.services.compute import get_session, run_session

logger = logging.getLogger(__name__)

USAGE = "usage: python -m api.compute_worker <session_id>"


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or not args[0].isdigit():
        raise SystemExit(USAGE)
    setup_logging()
    config = load_config()
    setup_logging(config.log_level)
    session_id = int(args[0])
    with closing(create_database_client(config.db)) as db, closing(create_sim_client(config.sim)) as sim:
        backend = get_session(db, session_id).backend
        with closing(create_compute_client(backend, config.compute, config.data_dir)) as compute:
            logger.info("GPU session %d: process running (%s)", session_id, backend)
            run_session(db, config, compute, sim, session_id)


if __name__ == "__main__":
    main()
