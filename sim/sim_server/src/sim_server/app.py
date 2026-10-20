"""Builds the sim server's FastAPI app. Run it with Isaac's interpreter, from the repo root:
"$ISAAC/python.sh" -m sim_server --port 9000. On the web-app machine: SIM_BACKEND=http SIM_URL=http://<instance>:9000
(the app appends /evaluate_batch). Reach the instance via a Brev Secure Link or `brev port-forward`; don't expose it.

There is no lifespan here, unlike the backend: the Scene (Isaac Sim) must start on the main thread before uvicorn does,
so __main__.py builds it and the SimQueue first and passes them in; they go on app.state for dependencies.py, with the
RecentBatches that answers a batch sent again after a lost connection.
"""

from fastapi import FastAPI

from sim_server.recent_batches import RecentBatches
from sim_server.routers import evaluations, health
from sim_server.scene import Scene
from sim_server.sim_queue import SimQueue


def create_app(scene: Scene, sim_queue: SimQueue) -> FastAPI:
    app = FastAPI(title="sim-server")
    app.state.scene, app.state.sim_queue, app.state.recent_batches = scene, sim_queue, RecentBatches()
    app.include_router(health.router)
    app.include_router(evaluations.router)
    return app
