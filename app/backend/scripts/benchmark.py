"""Run portable search comparisons without the web app or a physical robot."""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import tempfile
import time
import traceback
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import torch
from pydantic import SecretStr

from api.clients.benchmark import preflight, validate_url
from api.clients.cad import create_cad_client
from api.clients.database import DatabaseClient
from api.clients.sim import create_sim_client
from api.config import AppConfig, DbConfig, SimConfig, setup_logging
from api.models.benchmark import BenchmarkConfig
from api.services import benchmark, benchmark_report

ROOT = Path(__file__).resolve().parents[3]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--backend", choices=("mock", "http"), default="mock")
    parser.add_argument("--sim-url")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    if args.backend == "http" and not args.sim_url:
        parser.error("--backend http requires --sim-url")
    if args.sim_url:
        validate_url(args.sim_url)
    config = BenchmarkConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
    sim_config = SimConfig(backend=args.backend, url=args.sim_url, reconnect_minutes=0)
    output = args.output or ROOT / "app/data/benchmarks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    state = {
        "status": "incomplete",
        "badge": "mock" if args.backend == "mock" else "isaac",
        "config": config.model_dump(),
        "observations": [],
        "searches": [],
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "verification": "Local mock only"
        if args.backend == "mock"
        else "Server revision/reference CPU settings require operator verification",
    }
    started = time.perf_counter()
    if not args.dry_run:
        output.mkdir(parents=True, exist_ok=False)
        benchmark_report.checkpoint(output, state)
    try:
        with tempfile.TemporaryDirectory(prefix="finger-benchmark-") as temporary:
            directory = Path(temporary)
            app = AppConfig.model_construct(
                data_dir=directory, db=DbConfig(url=SecretStr(f"sqlite:///{directory.as_posix()}/app.db")), sim=sim_config
            )
            with closing(DatabaseClient(app.db)) as db, closing(create_cad_client()) as cad:
                run, prepared = benchmark.prepare(config, app, db, cad, ROOT)
            state["prepared"] = prepared
            state["estimate"] = benchmark.estimate(run, config)
            if args.dry_run:
                print(json.dumps(state["estimate"], indent=2))
                return 0
            state["versions"] = {name: importlib.metadata.version(name) for name in ("torch", "botorch", "gpytorch", "cadquery", "numpy")}
            state["versions"]["python"] = platform.python_version()
            state["runtime"] = {"torch_threads": torch.get_num_threads(), "platform": platform.platform(), "machine": platform.machine()}
            source_manifest = ROOT / "handoff-manifest.json"
            if source_manifest.is_file():
                state["archive_provenance"] = {
                    "revision": json.loads(source_manifest.read_text(encoding="utf-8")).get("revision"),
                    "manifest_sha256": hashlib.sha256(source_manifest.read_bytes()).hexdigest(),
                }
            source_files = [
                *sorted((ROOT / "app/backend/src").rglob("*.py")),
                *sorted((ROOT / "app/backend/scripts/benchmarks").glob("*.json")),
                Path(__file__).resolve(),
                ROOT / "uv.lock",
                ROOT / "pyproject.toml",
                ROOT / "app/backend/pyproject.toml",
            ]
            state["source_sha256"] = {
                path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files
            }
            state["git"] = {}
            for key, command in (
                ("revision", ["rev-parse", "HEAD"]),
                ("status", ["status", "--porcelain"]),
                ("diff", ["diff", "--binary", "HEAD"]),
            ):
                result = subprocess.run(["git", *command], cwd=ROOT, capture_output=True, text=True, timeout=30)
                state["git"][key] = result.stdout if result.returncode == 0 else "unavailable"
            if args.backend == "http":
                state["preflight"] = preflight(args.sim_url)
            with closing(create_sim_client(sim_config)) as sim:

                def save():
                    state["simulator"] = sim.describe()
                    state["wall_s"] = time.perf_counter() - started
                    benchmark_report.checkpoint(output, state)

                save()
                if args.preflight_only:
                    state["status"] = "preflight_only"
                else:
                    benchmark.execute(run, config, sim, state, save)
                    state["status"] = "complete"
                save()
    except BaseException as error:
        if args.dry_run:
            raise
        state["error"] = f"{type(error).__name__}: {error}"
        state["wall_s"] = time.perf_counter() - started
        benchmark_report.checkpoint(output, state)
        benchmark_report.report(output, state)
        traceback.print_exc()
        return 1
    benchmark_report.report(output, state)
    print(f"{state['badge'].upper()} {state['status']}: {output.resolve()}")
    return 0


if __name__ == "__main__":
    setup_logging()
    raise SystemExit(main())
