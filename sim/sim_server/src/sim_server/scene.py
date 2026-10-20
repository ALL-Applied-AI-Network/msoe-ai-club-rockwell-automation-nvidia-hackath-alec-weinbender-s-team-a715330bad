"""The Isaac Sim app's lifecycle: start SimulationApp, build the grasp cell (clients/isaac.py), close both. Loaded once and
kept between requests.

This module and clients/isaac.py are the only ones that touch Isaac, and this one only inside load_scene(): importing it
is Isaac-free, so the HTTP layer and its tests can load it anywhere. Isaac isn't importable from the uv venv; it ships its
own interpreter. Install this package into it and start the server with "$ISAAC/python.sh" -m sim_server (see
sim/README.md). Everything that drives Isaac runs on the main thread, via SimQueue.
"""

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sim_server.twin import use_twin

logger = logging.getLogger(__name__)

FRICTION_COMBINE_MODES = ("average", "min", "multiply", "max")


@dataclass(frozen=True)
class SceneConfig:
    """envs = 1 is the reference path (the twin's own robot, one grasp at a time); envs > 1 the vectorised path."""

    envs: int = 1
    device: str = "cpu"  # "cpu" or "cuda:N"
    env_spacing: float = 2.0  # metres between environment copies
    friction_combine: str = "average"  # how PhysX combines custom-finger friction with the part's (see sim/README.md)
    twin_dir: Path | None = None  # default: sim/fanuc_er4ia_sim in this repo
    headless: bool = True


@dataclass
class Scene:
    app: Any  # isaacsim.SimulationApp
    cell: Any = field(repr=False)  # clients/isaac.GraspCell, which services/evaluations.evaluate_batch runs batches on

    def describe(self) -> dict:
        return self.cell.describe()

    def close(self) -> None:
        self.app.close()


def load_scene(config: SceneConfig) -> Scene:
    """Starts Isaac Sim and builds the cell. Startup is the expensive part, so the server does it once, before serving."""
    use_twin(config.twin_dir)  # before Isaac starts, so a wrong path fails in a second rather than a minute
    if config.friction_combine not in FRICTION_COMBINE_MODES:
        raise ValueError(f"friction_combine must be one of {FRICTION_COMBINE_MODES}")
    try:
        from isaacsim import SimulationApp  # must be started before any other omni/pxr import
    except ImportError as e:
        raise RuntimeError(
            f"Isaac Sim isn't importable from {sys.executable}. It ships its own interpreter: install this package into it with "
            '"$ISAAC/python.sh" -m pip install -e sim/sim_server, then start the server with "$ISAAC/python.sh" -m sim_server.'
        ) from e
    logger.info("Starting Isaac Sim (headless=%s)", config.headless)
    app = SimulationApp({"headless": config.headless})
    try:
        from sim_server.clients.isaac import GraspCell  # imports omni and pxr, so only once the app is running

        cell = GraspCell(envs=config.envs, device=config.device, env_spacing=config.env_spacing, friction_combine=config.friction_combine)
    except Exception:
        logger.exception("Building the grasp cell failed")  # Kit can end the process on close before a traceback prints
        app.close()
        raise
    return Scene(app, cell)
