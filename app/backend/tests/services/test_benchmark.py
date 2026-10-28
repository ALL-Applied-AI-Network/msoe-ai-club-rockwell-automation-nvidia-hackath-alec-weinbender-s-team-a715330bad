import importlib.util
import io
import json
import random
from pathlib import Path

import pytest

from api.clients.benchmark import preflight, validate_url
from api.clients.sim import MockSim, SimError
from api.models.benchmark import BenchmarkConfig
from api.models.outcome import Outcomes
from api.models.search_plan import SearchConfig
from api.services import benchmark, benchmark_report, optimizer

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def prepared(config, db, cad):
    return benchmark.prepare(BenchmarkConfig(budget=15, seeds=[0]), config, db, cad, ROOT)[0]


@pytest.fixture
def runner():
    spec = importlib.util.spec_from_file_location("benchmark_script", ROOT / "app/backend/scripts/benchmark.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_schedule_and_estimate(prepared):
    config = BenchmarkConfig(budget=15, seeds=[0])
    counts = benchmark.schedule(prepared, config)
    assert counts == [12, 1, 1, 1]
    assert sum(counts) == config.budget
    estimate = benchmark.estimate(prepared, config)
    assert estimate["candidate_evaluations"] == 45
    assert estimate["maximum_simulator_grasps"] == 47 * 243 + 26 * 963


def test_three_methods_budget_finalists_repeats(prepared, monkeypatch, tmp_path):
    def proposal(space, history, count, *, seed, round_number, diagnostics):
        diagnostics.update(source="bo", fallback_reason=None)
        return optimizer._sobol(len(space.names), count, seed, skip=len(history))

    monkeypatch.setattr(optimizer, "_propose", proposal)
    monkeypatch.setattr(SearchConfig, "stop_reason", lambda self, scores: "patience")
    config = BenchmarkConfig(budget=15, seeds=[0, 1])
    state = {"config": config.model_dump(), "badge": "mock", "status": "complete", "observations": [], "searches": []}
    checkpoints = []
    benchmark.execute(prepared, config, MockSim(), state, lambda: checkpoints.append(len(state["observations"])))
    for seed in config.seeds:
        initial = []
        for method in benchmark.METHODS:
            rows = [row for row in state["observations"] if row["seed"] == seed and row["method"] == method]
            search = [row for row in rows if row["phase"] == "search"]
            assert len(search) == 15
            initial.append([row["design"] for row in search[:12]])
            assert len([row for row in rows if row["phase"] == "final"]) == 3
            assert len([row for row in rows if row["phase"] == "repeat"]) == 3
            assert search[-1]["cumulative_grasps"] == sum(row["grasps"] for row in search)
            summary = next(item for item in state["searches"] if item["seed"] == seed and item["method"] == method)
            assert summary["patience_would_stop_at"] == 12
            assert summary["winner"]["success_rate"] == max(row["success_rate"] for row in rows if row["phase"] == "final")
        assert initial[0] == initial[1] == initial[2]
    assert [item["method"] for item in state["searches"]] == ["bo", "sobol", "ga", "sobol", "ga", "bo"]
    assert checkpoints == sorted(checkpoints)
    benchmark_report.checkpoint(tmp_path, state)
    benchmark_report.report(tmp_path, state)
    assert json.loads((tmp_path / "results.json").read_text())["status"] == "complete"
    assert "MOCK" in (tmp_path / "convergence-grasps.svg").read_text()
    assert "badge,status" in (tmp_path / "candidates.csv").read_text()
    assert "Paired" in (tmp_path / "report.md").read_text()


def test_partial_batch_and_small_budget(prepared):
    prepared.job.plan.searches[0].batch_size = 4
    assert benchmark.schedule(prepared, BenchmarkConfig(budget=19)) == [12, 4, 3]
    assert benchmark.schedule(prepared, BenchmarkConfig(budget=1)) == [1]


def test_method_order_survives_running_seeds_as_separate_jobs(prepared):
    state = {"observations": [], "searches": []}
    benchmark.execute(prepared, BenchmarkConfig(budget=1, seeds=[1]), MockSim(), state, lambda: None)
    assert [search["method"] for search in state["searches"]] == ["sobol", "ga", "bo"]


def test_repeated_selection_rejects_a_lucky_single_run(prepared):
    space = next(iter(prepared.spaces.values()))
    designs = [space.from_unit(point) for point in optimizer._sobol(len(space.names), 2, 0)]
    observations = benchmark.evaluate(
        prepared, MockSim(), designs, prepared.job.plan.final_grid, seed=0, method="bo", phase="final", batch=0, earlier=[]
    )
    lucky, stable = observations
    repeats = [lucky.model_copy(update={"success_rate": score, "number": index}) for index, score in enumerate((0.95, 0.10, 0.10))]
    repeats += [stable.model_copy(update={"success_rate": 0.65, "number": index + 3}) for index in range(3)]
    winner, summary = benchmark.select_winner(repeats)
    assert winner.parameter_hash == stable.parameter_hash
    assert summary["mean"] == 0.65 and summary["sd"] == 0 and summary["repeats"] == 3
    assert max(repeats, key=lambda row: row.success_rate).parameter_hash == lucky.parameter_hash


def test_finalists_use_unique_buildable_geometry(prepared):
    space = next(iter(prepared.spaces.values()))
    designs = [space.from_unit(point) for point in optimizer._sobol(len(space.names), 2, 0)]
    observations = benchmark.evaluate(
        prepared, MockSim(), designs, prepared.job.plan.grid, seed=0, method="bo", phase="search", batch=0, earlier=[]
    )
    first, second = observations
    duplicate = first.model_copy(update={"number": 3, "success_rate": 1.0, "parameter_hash": "other-params"})
    rejected = first.model_copy(update={"number": 4, "success_rate": 1.0, "geometry_hash": None})
    finalists = benchmark.unique_finalists([first, second, duplicate, rejected])
    assert len(finalists) == 2
    assert finalists[0].parameter_hash == "other-params"
    assert len({row.geometry_hash for row in finalists}) == 2
    with pytest.raises(ValueError, match="buildable"):
        benchmark.unique_finalists([rejected])


def test_repeated_selection_budget_and_holdout_separation(prepared, tmp_path):
    config = BenchmarkConfig(budget=2, seeds=[0], selection_repeats=3)
    state = {"observations": [], "searches": []}
    benchmark.execute(prepared, config, MockSim(), state, lambda: None)
    rows = state["observations"]
    assert len(rows) == 47
    assert sum(row["grasps"] for row in rows) == benchmark.estimate(prepared, config)["maximum_simulator_grasps"]
    for method in benchmark.METHODS:
        selection = [row for row in rows if row["method"] == method and row["phase"] == "final"]
        holdout = [row for row in rows if row["method"] == method and row["phase"] == "repeat"]
        assert len(selection) == 6 and len(holdout) == 3
        summary = next(search for search in state["searches"] if search["method"] == method)
        assert summary["selection"]["repeats"] == 3
    for row in rows:
        if row["phase"] == "repeat":
            row["success_rate"] = 0.2
    for search in state["searches"]:
        search["selection"]["mean"] = {"bo": 0.99, "sobol": 0.1, "ga": 0.7}[search["method"]]
    state.update(config=config.model_dump(), status="complete", badge="mock")
    benchmark_report.report(tmp_path, state)
    text = (tmp_path / "report.md").read_text()
    assert "Seed 0, bo: +0.000000" in text and "Seed 0, ga: +0.000000" in text


def test_cube16_pilot_is_bounded_and_explicit(config, db, cad):
    specification = BenchmarkConfig(case="cube16", budget=14, seeds=[0], selection_repeats=3, pilot=True)
    run, metadata = benchmark.prepare(specification, config, db, cad, ROOT)
    assert run.job.part.extent_mm[0] == pytest.approx(16, abs=0.01)
    assert run.job.plan.grid.size == run.job.plan.final_grid.size == 3
    estimate = benchmark.estimate(run, specification)
    assert estimate["maximum_simulator_grasps"] == 276
    assert estimate["grid_kind"] == "pilot diagnostic"
    assert any("PILOT" in warning for warning in metadata["plan"]["warnings"])


def test_preflight_only_runner(runner, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("preflight ran simulations")

    monkeypatch.setattr(runner.benchmark, "execute", forbidden)
    monkeypatch.setattr(runner, "preflight", lambda url: {"status": "ok", "device": "cpu", "envs": 64})
    output = tmp_path / "preflight"
    assert (
        runner.main(
            [
                str(ROOT / "app/backend/scripts/benchmarks/cube-quick.json"),
                "--preflight-only",
                "--backend",
                "http",
                "--sim-url",
                "http://localhost:9011",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    state = json.loads((output / "results.json").read_text())
    assert state["badge"] == "isaac" and state["status"] == "preflight_only"
    assert not state["observations"]


def test_genetic_deterministic_bounded_and_elitist(prepared):
    space = next(iter(prepared.spaces.values()))
    designs = [space.from_unit(point) for point in optimizer._sobol(len(space.names), 12, 0)]
    history = benchmark.evaluate(
        prepared, MockSim(), designs, prepared.job.plan.grid, seed=0, method="ga", phase="search", batch=0, earlier=[]
    )
    first = benchmark.genetic(space, history, 50, 12, random.Random(7))
    assert first == benchmark.genetic(space, history, 50, 12, random.Random(7))
    assert all(0 <= value <= 1 for point in first for value in point)
    tied = [row.model_copy(update={"success_rate": 1.0}) for row in history]
    only_first = benchmark.genetic(space, tied, 5, 1, random.Random(3))
    assert only_first == benchmark.genetic(space, tied[:1], 5, 1, random.Random(3))


def test_rejections_duplicates_and_fallback(prepared, monkeypatch):
    space = next(iter(prepared.spaces.values()))
    design = space.centre()
    rows = benchmark.evaluate(
        prepared, MockSim(), [design, design], prepared.job.plan.grid, seed=0, method="bo", phase="search", batch=0, earlier=[]
    )
    assert rows[1].duplicate_parameters and rows[1].duplicate_geometry
    monkeypatch.setattr(optimizer, "problems", lambda *args, **kwargs: ["test rejection"])
    rejected = benchmark.evaluate(
        prepared, MockSim(), [design], prepared.job.plan.grid, seed=0, method="bo", phase="search", batch=1, earlier=rows
    )[0]
    assert rejected.grasps == rejected.simulator_s == rejected.success_rate == 0
    assert rejected.geometry_hash is None

    def broken(*args, **kwargs):
        raise RuntimeError("test GP failure")

    monkeypatch.setattr(optimizer, "SingleTaskGP", broken)
    diagnostics = {}
    points = optimizer._propose(space, rows, 2, seed=0, round_number=1, diagnostics=diagnostics)
    assert points == optimizer._sobol(len(space.names), 2, 0, skip=2)
    assert diagnostics == {"source": "sobol_fallback", "fallback_reason": "RuntimeError: test GP failure"}


def test_landing_is_scored_as_miss(prepared, monkeypatch):
    design = next(iter(prepared.spaces.values())).centre()
    count = prepared.job.plan.grid.size
    outcome = Outcomes(held=[True] * count, in_hand=[(0, 0, 0, 0, 0)] * count, landing=[(2.0, 0.0)] * count)

    def simulate(run, sim, designs, grid, diagnostics):
        diagnostics.append({"rejections": [], "finger": None, "geometry_s": 0.0, "simulated_grasps": count})
        return [[outcome]], [1.0]

    monkeypatch.setattr(optimizer, "_simulate", simulate)
    row = benchmark.evaluate(
        prepared, MockSim(), [design], prepared.job.plan.grid, seed=0, method="bo", phase="search", batch=0, earlier=[]
    )[0]
    assert row.success_rate == 0 and row.grasps == count
    assert all(row.outcomes.held)
    assert row.outcomes.landing is not None


def test_screw_preparation_keeps_grasp_span(config, db, cad):
    run, metadata = benchmark.prepare(BenchmarkConfig(case="screw", budget=14, seeds=[0]), config, db, cad, ROOT)
    assert run.job.spec.grasp.model_dump(mode="json")["span_mm"] == metadata["grasp"]["span_mm"]
    assert metadata["spec"]["error"] is not None
    assert len(run.job.poses) == 1


def test_dry_run_isolated_and_no_simulator(runner, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run contacted simulator")

    monkeypatch.setattr(runner, "preflight", forbidden)
    monkeypatch.setattr(runner, "create_sim_client", forbidden)
    output = tmp_path / "not-created"
    assert (
        runner.main(
            [
                str(ROOT / "app/backend/scripts/benchmarks/cube-quick.json"),
                "--dry-run",
                "--backend",
                "http",
                "--sim-url",
                "http://localhost:9011",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert not output.exists()


def test_failure_artifacts_and_overwrite(runner, tmp_path, monkeypatch):
    class FailingSim(MockSim):
        calls = 0

        def run_batch(self, *args):
            self.calls += 1
            if self.calls == 3:
                raise SimError("test interrupted connection")
            return super().run_batch(*args)

    monkeypatch.setattr(runner, "create_sim_client", lambda config: FailingSim())
    monkeypatch.setattr(optimizer, "_propose", lambda space, trials, count, **kwargs: optimizer._sobol(len(space.names), count, 0))
    output = tmp_path / "failed"
    args = [str(ROOT / "app/backend/scripts/benchmarks/cube-quick.json"), "--output", str(output)]
    assert runner.main(args) == 1
    state = json.loads((output / "results.json").read_text())
    assert state["status"] == "incomplete" and state["observations"]
    assert "interrupted" in state["error"]
    with pytest.raises(FileExistsError):
        runner.main(args)


def test_preflight_identity(monkeypatch):
    metadata = {"status": "ok", "envs": 64, "device": "cpu", "friction_combine": "average"}
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: io.BytesIO(json.dumps(metadata).encode()))
    assert preflight("http://localhost:9011") == metadata
    metadata.pop("device")
    with pytest.raises(ValueError, match="identify"):
        preflight("http://localhost:9011")
    with pytest.raises(ValueError):
        validate_url("http://user:secret@localhost:9011")


@pytest.mark.parametrize("seeds", [[0, 0], [-1], []])
def test_invalid_seeds(seeds):
    with pytest.raises(ValueError):
        BenchmarkConfig(seeds=seeds)
