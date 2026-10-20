"""Finds the vendored FANUC ER-4iA twin (sim/fanuc_er4ia_sim) and makes its modules importable. Isaac-free.

The twin isn't a package: its modules import each other as top-level modules (`import cell`, `import scene_config as C`),
and they're meant to run from inside its directory. We treat it as upstream code and never edit it, so instead of copying
or patching it we put its directory at the front of sys.path, once, before anything imports it.

The default is the copy in this repo, found relative to this file. That only works with an editable install
(`pip install -e sim/sim_server`, or `uv sync`); otherwise pass the directory explicitly (`python -m sim_server --twin-dir`).
"""

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# src/sim_server/twin.py -> parents[3] is sim/
DEFAULT_TWIN_DIR = Path(__file__).resolve().parents[3] / "fanuc_er4ia_sim"
_REQUIRED = ("scene_config.py", "cell.py", "ik.py", "fk.py", "gripper_geometry.py")


def use_twin(twin_dir: Path | str | None = None) -> Path:
    """Puts the twin's directory on sys.path and returns it. Idempotent; refuses to mix two different twin copies."""
    path = Path(twin_dir or DEFAULT_TWIN_DIR).resolve()
    missing = [name for name in _REQUIRED if not (path / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"{path} isn't the FANUC ER-4iA twin (missing {', '.join(missing)}). Pass the directory that holds "
            "scene_config.py and cell.py with --twin-dir (default: sim/fanuc_er4ia_sim next to this package)."
        )
    loaded = sys.modules.get("scene_config")
    if loaded is not None and Path(loaded.__file__).resolve().parent != path:
        raise RuntimeError(f"scene_config is already imported from {Path(loaded.__file__).parent}, not {path}")
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
        logger.info("Twin modules import from %s", path)
    return path
