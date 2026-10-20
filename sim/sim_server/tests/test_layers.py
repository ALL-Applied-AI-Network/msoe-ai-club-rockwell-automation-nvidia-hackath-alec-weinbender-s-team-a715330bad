"""The package's layering rules, checked from each module's imports:

- only clients/isaac.py and scene.py touch Isaac (omni, pxr, isaacsim, carb, or the twin's Isaac-bound cell module);
- FastAPI only in the HTTP layer (app.py, dependencies.py, routers/);
- routers -> services -> robot / clients -> models, one direction: services get the Isaac client handed in (its Cell
  protocol), never import it; clients never import services; models import no other layer;
- the HTTP layer's import chain stays numpy-free (numpy comes with Isaac's Python; the routes shouldn't need it).
"""

import ast
import functools
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE = Path(importlib.import_module("sim_server").__file__).parent
ISAAC = {"omni", "pxr", "isaacsim", "carb", "cell"}  # "cell" is the twin's cell.py, which imports pxr at the top
HTTP = {"fastapi", "starlette", "uvicorn"}
HTTP_LAYER = ("sim_server.routers", "sim_server.app", "sim_server.dependencies")


@functools.cache
def modules() -> dict[str, set[str]]:
    """Every module (path relative to the package, e.g. 'clients/isaac.py') -> the modules it imports, at any depth."""
    found = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        imported = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imported.add(node.module)
        found[path.relative_to(PACKAGE).as_posix()] = imported
    return found


def roots(imported: set[str]) -> set[str]:
    return {name.split(".")[0] for name in imported}


def ours(imported: set[str], *layers: str) -> set[str]:
    """The package's own imports that fall in these layers."""
    return {name for name in imported if name.startswith(tuple(f"sim_server.{layer}" for layer in layers))}


@pytest.mark.parametrize("module", sorted(modules()))
def test_isaac_only_where_allowed(module):
    if module not in ("clients/isaac.py", "scene.py"):
        assert not roots(modules()[module]) & ISAAC
    else:
        assert roots(modules()[module]) & ISAAC  # the scan does see Isaac imports, including scene.py's lazy ones


@pytest.mark.parametrize("module", sorted(modules()))
def test_layers_point_one_way(module):
    imported = modules()[module]
    if module.startswith("models/"):
        assert all(name.startswith("sim_server.models") for name in imported if name.startswith("sim_server"))
        assert not roots(imported) & (HTTP | ISAAC | {"numpy"})
    if module.startswith("robot/"):
        assert not ours(imported, "services", "clients", "routers", "app", "dependencies")
    if module.startswith("clients/"):
        assert not ours(imported, "services", "routers", "app", "dependencies")
    if module.startswith("services/"):
        assert not ours(imported, "clients", "routers", "app", "dependencies")
    if module.startswith("routers/"):
        assert not ours(imported, "clients", "robot.motion")  # the Isaac client, and numpy
    if not (module.startswith("routers/") or module in ("app.py", "dependencies.py", "__main__.py")):
        assert not roots(imported) & HTTP
        assert not any(name.startswith(HTTP_LAYER) for name in imported)


def test_the_http_layer_imports_without_numpy_or_isaac():
    code = "import sys, sim_server.app; print(sorted(m for m in ('numpy', 'pxr', 'omni', 'isaacsim') if m in sys.modules))"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "[]"
