"""Entry point. From the repo root, with Isaac's interpreter:  "$ISAAC/python.sh" -m sim_server [--envs N] [--port 9000]

--envs 1 (default) is the reference path: the twin's own robot on CPU physics, one grasp at a time. --envs N > 1 is the
vectorised path: N copies of the robot and part, stepped together on GPU physics.

Isaac Sim gets the main thread: it starts there and every grasp batch runs there (sim_queue.py). Uvicorn serves HTTP from
a background thread and hands batches over through the queue.
"""

import argparse
import logging
import threading
from pathlib import Path

import uvicorn

from sim_server.app import create_app
from sim_server.scene import FRICTION_COMBINE_MODES, SceneConfig, load_scene
from sim_server.sim_queue import SimQueue

logger = logging.getLogger("sim_server")


def main() -> None:
    parser = argparse.ArgumentParser(prog="sim_server", description="Grasp-evaluation server for the FANUC ER-4iA twin")
    parser.add_argument("--host", default="127.0.0.1", help="0.0.0.0 only when a firewall keeps the port private")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--envs", type=int, default=1, help="1: reference path (one grasp at a time); N > 1: N parallel copies")
    parser.add_argument("--device", default="auto", help="cpu, cuda:0, ... (auto: cpu for --envs 1, cuda:0 otherwise)")
    parser.add_argument("--env-spacing", type=float, default=2.0, help="metres between copies (vectorised path)")
    parser.add_argument(
        "--friction-combine",
        choices=FRICTION_COMBINE_MODES,
        default="average",
        help="how PhysX combines custom-finger friction with the part's (the request's part friction, or the twin's 0.9/0.8); "
        "set on both materials. max = the twin's soft-tip convention",
    )
    parser.add_argument("--twin-dir", type=Path, default=None, help="the twin's directory (default: sim/fanuc_er4ia_sim in this repo)")
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.envs < 1:
        parser.error("--envs must be at least 1")
    device = ("cpu" if args.envs == 1 else "cuda:0") if args.device == "auto" else args.device
    if device != "cpu" and not device.startswith("cuda"):
        parser.error("--device must be cpu or cuda[:N]")
    config = SceneConfig(
        envs=args.envs, device=device, env_spacing=args.env_spacing, friction_combine=args.friction_combine, twin_dir=args.twin_dir
    )
    logger.info("Starting with %s", config)

    scene = load_scene(config)
    sim_queue = SimQueue()
    # loop="asyncio": with uvloop installed (uvicorn[standard]), "auto" sets uvloop's event-loop policy for the whole
    # process, and Kit's extensions on the main thread then fail in asyncio.get_event_loop() on every stage edit.
    http_config = uvicorn.Config(
        create_app(scene, sim_queue), host=args.host, port=args.port, log_level=args.log_level.lower(), loop="asyncio"
    )
    server = uvicorn.Server(http_config)
    http = threading.Thread(target=server.run, name="http", daemon=True)
    http.start()
    try:
        sim_queue.serve(keep_running=http.is_alive)
        logger.error("HTTP server stopped; shutting down")
    except KeyboardInterrupt:
        logger.info("Interrupted; shutting down")
    finally:
        server.should_exit = True
        sim_queue.close()  # fail queued batches first, or uvicorn waits on their requests
        http.join(timeout=10)
        scene.close()


if __name__ == "__main__":
    main()
