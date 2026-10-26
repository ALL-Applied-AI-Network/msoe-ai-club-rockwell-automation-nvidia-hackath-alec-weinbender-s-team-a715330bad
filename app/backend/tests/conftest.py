import dataclasses
import os
import shutil
from dataclasses import dataclass

import cadquery as cq
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.clients.cad import CadQueryCad
from api.clients.compute import MockCompute
from api.clients.database import DatabaseClient
from api.clients.sim import MockSim, SimError, SimRecording
from api.config import AppConfig
from api.db.tables import CellProfileRow, JobRow
from api.dependencies import get_cad, get_compute, get_config, get_db
from api.main import app
from api.models.grasp import GraspChoice
from api.models.job_spec import JobSpec
from api.services import cell_profiles, compute, jobs

APP_VARIABLES = ("ANTHROPIC_API_KEY", "DATA_DIR", "LOG_LEVEL")


@pytest.fixture(autouse=True, scope="session")
def _isolated_from_developer_settings():
    """Tests never read the developer's .env or exported app variables."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(AppConfig.model_config, "env_file", None)
        for name in list(os.environ):
            if name.startswith(("LLM_", "SIM_", "COMPUTE_")) or name in APP_VARIABLES:
                mp.delenv(name)
        yield


@pytest.fixture
def config(tmp_path) -> AppConfig:
    """Mock backends (the defaults) and a temporary data directory."""
    return AppConfig(data_dir=tmp_path)


@pytest.fixture
def db(config) -> DatabaseClient:
    """A fresh SQLite file in the temporary data directory, built by running the real migrations."""
    database = DatabaseClient(config.db)
    database.migrate()
    yield database
    database.close()


@pytest.fixture
def profile_id(db) -> int:
    """The default cell profile ("UWM CSI cell"), seeded as at API startup: its version id."""
    cell_profiles.ensure_default_profile(db)
    with db.session() as s:
        return s.scalar(select(CellProfileRow.id))


@pytest.fixture(scope="session")
def cad() -> CadQueryCad:
    return CadQueryCad()


@pytest.fixture
def spawned(monkeypatch) -> list[tuple[str, ...]]:
    """Stops services from launching real worker processes. Records (job_id, *args) instead."""
    started = []
    monkeypatch.setattr(jobs, "spawn_worker", lambda db, config, job_id, *args: started.append((job_id, *args)))
    return started


@pytest.fixture
def spawned_sessions(monkeypatch) -> list[int]:
    """Stops services from launching real GPU session processes. Records the session ids instead."""
    started = []
    monkeypatch.setattr(compute, "spawn_session", lambda db, config, session_id: started.append(session_id))
    return started


@pytest.fixture
def compute_client(config) -> MockCompute:
    """The mock compute backend, its made-up instances' states kept in the temporary data directory."""
    return MockCompute(config.data_dir / "mock_compute.json")


@pytest.fixture
def client(config, db, cad, spawned, spawned_sessions, compute_client):
    """The API over the temporary database. The lifespan doesn't run, so nothing reads the real config."""
    app.dependency_overrides = {
        get_config: lambda: config,
        get_db: lambda: db,
        get_cad: lambda: cad,
        get_compute: lambda: {"mock": compute_client},
    }
    yield TestClient(app)
    app.dependency_overrides = {}


# Test parts, built with CadQuery, in mm, as authored. The cap is cup-shaped like the yellow vial caps on the cell; the
# tube lies along x; the plate is too wide for these fingers lying flat, but not standing on an edge; the bar comes to
# rest on its side (pose 0, 87%) or standing (pose 1, 13%), and is 10 mm across both ways.
SHAPES = {
    "cube": lambda: cq.Workplane("XY").box(10, 10, 10),
    "bar": lambda: cq.Workplane("XY").box(10, 10, 20),
    "vial_cap": lambda: cq.Workplane("XY").circle(15.875).extrude(15.7).faces(">Z").workplane().hole(28.0, 13.7),
    "glass_tube": lambda: cq.Workplane("YZ").circle(8.5).extrude(140),
    "l_bracket": lambda: cq.Workplane("XY").polyline([(0, 0), (30, 0), (30, 6), (6, 6), (6, 20), (0, 20)]).close().extrude(12),
    "wide_plate": lambda: cq.Workplane("XY").box(120, 120, 4),
}


@pytest.fixture(scope="session")
def shapes() -> dict[str, cq.Workplane]:
    """The test parts by name: cube, bar, vial_cap, glass_tube, l_bracket, wide_plate."""
    return {name: make() for name, make in SHAPES.items()}


@pytest.fixture
def step_file(tmp_path):
    """step_file(shape, name="part.step") -> the bytes of that shape as a STEP file, as a user would upload it."""

    def write(shape: cq.Workplane | cq.Shape, name: str = "part.step") -> bytes:
        path = tmp_path / name
        cq.exporters.export(shape, str(path))
        return path.read_bytes()

    return write


@pytest.fixture
def stl_file(tmp_path):
    """stl_file(shape, name="part.stl", scale=1.0) -> the bytes of an STL; scale=1/25.4 makes one in inches."""

    def write(shape: cq.Workplane | cq.Shape, name: str = "part.stl", scale: float = 1.0) -> bytes:
        solid = shape.val() if isinstance(shape, cq.Workplane) else shape
        if scale != 1.0:
            solid = solid.scale(scale)
        path = tmp_path / name
        cq.exporters.export(solid, str(path), tolerance=0.01, angularTolerance=0.1)
        return path.read_bytes()

    return write


@dataclass(frozen=True)
class FinishedJob:
    config: AppConfig
    db: DatabaseClient
    job_id: str
    part_id: str
    profile_id: int


FINISHED_BUDGET = 18  # the vial cap has 6 free parameters: 16 Sobol designs in round 0, then two GP rounds of one


@pytest.fixture(scope="session")
def finished_job(tmp_path_factory, cad) -> FinishedJob:
    """A vial-cap experiment run to the end on the mock sim (a Sobol round, two GP rounds, the final test and D1's CAD) in
    its own database, for tests that only read it. Shared by the whole session: don't change it."""
    from api.clients.sim import MockSim
    from api.services import parts
    from api.services.optimizer import run_job  # here, so only the tests that need it pay for importing torch

    config = AppConfig(data_dir=tmp_path_factory.mktemp("finished"))
    database = DatabaseClient(config.db)
    database.migrate()
    cell_profiles.ensure_default_profile(database)
    profile = cell_profiles.list_profiles(database)[0]
    path = config.data_dir / "vial_cap.step"
    cq.exporters.export(SHAPES["vial_cap"](), str(path))
    record = parts.create_part(database, config, cad, path.name, path.read_bytes(), None)
    parts.update_part(database, record.id, {"material": "pla", "pose": 0})
    best = parts.propose_grasps(database, record.id, profile.profile).candidates[0]
    grasp = GraspChoice(angle_deg=best.angle_deg, centre_mm=best.centre_mm)
    spec = JobSpec(part_id=record.id, cell_profile_id=profile.id, grasp=grasp, budget=FINISHED_BUDGET)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(jobs, "spawn_worker", lambda *args: None)
        job = jobs.create_job(database, config, spec)
    run_job(database, job.id, sim=MockSim(), cad=cad, outputs_dir=config.outputs_dir)
    assert jobs.get_job(database, job.id).status == "done"
    yield FinishedJob(config, database, job.id, record.id, profile.id)
    database.close()


@pytest.fixture(scope="session")
def two_pose_job(tmp_path_factory, cad) -> FinishedJob:
    """A bar experiment over two resting poses, on its side (the primary, 87%) and standing (13%), run to the end on the
    mock sim in its own database, for tests that only read it. Shared by the whole session: don't change it."""
    from api.clients.sim import MockSim
    from api.models.job_spec import PoseGrasp
    from api.services import parts
    from api.services.optimizer import run_job

    config = AppConfig(data_dir=tmp_path_factory.mktemp("two_poses"))
    database = DatabaseClient(config.db)
    database.migrate()
    cell_profiles.ensure_default_profile(database)
    profile = cell_profiles.list_profiles(database)[0]
    path = config.data_dir / "bar.step"
    cq.exporters.export(SHAPES["bar"](), str(path))
    record = parts.create_part(database, config, cad, path.name, path.read_bytes(), None)
    parts.update_part(database, record.id, {"material": "pla"})
    poses = [PoseGrasp(pose=0, grasp=GraspChoice(angle_deg=90)), PoseGrasp(pose=1, grasp=GraspChoice(angle_deg=0))]
    spec = JobSpec(part_id=record.id, cell_profile_id=profile.id, poses=poses, budget=14)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(jobs, "spawn_worker", lambda *args: None)
        job = jobs.create_job(database, config, spec)
    run_job(database, job.id, sim=MockSim(), cad=cad, outputs_dir=config.outputs_dir)
    assert jobs.get_job(database, job.id).status == "done"
    yield FinishedJob(config, database, job.id, record.id, profile.id)
    database.close()


@pytest.fixture
def finished_client(finished_job, cad):
    """The API over the finished job's database, for read-only route tests."""
    app.dependency_overrides = {get_config: lambda: finished_job.config, get_db: lambda: finished_job.db, get_cad: lambda: cad}
    yield TestClient(app)
    app.dependency_overrides = {}


@pytest.fixture
def two_pose_client(two_pose_job, cad):
    """The API over the two-pose job's database, for read-only route tests."""
    app.dependency_overrides = {get_config: lambda: two_pose_job.config, get_db: lambda: two_pose_job.db, get_cad: lambda: cad}
    yield TestClient(app)
    app.dependency_overrides = {}


@dataclass(frozen=True)
class EvaluatedPart:
    config: AppConfig
    db: DatabaseClient
    job_id: str  # the evaluation job, done
    generation_job_id: str  # the generation job whose D1 is in the library
    part_id: str  # the 10 mm cube
    profile_id: int
    stock_id: str
    generated_id: str  # D1 of the generation job
    uploaded_id: str  # a flat 12 x 6 x 76 mm blade, uploaded as a STEP


# One finger as authored for an upload: a flat blade with its gripping face 2 mm off the file's origin plane
FLAT_FINGER = lambda: cq.Workplane("XY").box(12, 6, 76).translate((8, 0, 38))  # noqa: E731


def _evaluated(config: AppConfig, cad) -> EvaluatedPart:
    from api.clients.sim import MockSim
    from api.models.evaluation import EvaluationSpec
    from api.services import fingers, parts
    from api.services.optimizer import run_job

    database = DatabaseClient(config.db)
    database.migrate()
    cell_profiles.ensure_default_profile(database)
    fingers.ensure_stock_fingers(database)
    profile = cell_profiles.list_profiles(database)[0]
    path = config.data_dir / "cube.step"
    cq.exporters.export(SHAPES["cube"](), str(path))
    record = parts.create_part(database, config, cad, path.name, path.read_bytes(), None)
    parts.update_part(database, record.id, {"material": "pla", "pose": 0})
    best = parts.propose_grasps(database, record.id, profile.profile).candidates[0]
    spec = JobSpec(
        part_id=record.id, cell_profile_id=profile.id, grasp=GraspChoice(angle_deg=best.angle_deg, centre_mm=best.centre_mm), budget=8
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(jobs, "spawn_worker", lambda *args: None)
        generation = jobs.create_job(database, config, spec)
        run_job(database, generation.id, sim=MockSim(), cad=cad, outputs_dir=config.outputs_dir)
        generated = fingers.add_from_job(database, generation.id, "D1")
        flat = config.data_dir / "flat_finger.step"
        cq.exporters.export(FLAT_FINGER(), str(flat))
        uploaded = fingers.create_finger(database, config, cad, flat.name, flat.read_bytes(), cell_profile_id=profile.id, family="flat")
        evaluation = jobs.create_job(database, config, EvaluationSpec(part_id=record.id, cell_profile_id=profile.id))
        run_job(database, evaluation.id, sim=MockSim(), cad=cad, outputs_dir=config.outputs_dir)
    assert jobs.get_job(database, evaluation.id).status == "done"
    stock = next(r for r, _ in fingers.list_fingers(database) if r.source == "stock")
    return EvaluatedPart(config, database, evaluation.id, generation.id, record.id, profile.id, stock.id, generated.id, uploaded.id)


@pytest.fixture(scope="session")
def evaluated(tmp_path_factory, cad) -> EvaluatedPart:
    """A 10 mm cube evaluated on the mock sim against a library of three fingers (the stock ones, D1 of a short
    generation job on the cube, and an uploaded flat blade), in its own database, for tests that only read it. Shared by
    the whole session: don't change it (evaluated_copy is a copy to change)."""
    part = _evaluated(AppConfig(data_dir=tmp_path_factory.mktemp("evaluated")), cad)
    yield part
    part.db.close()


@pytest.fixture
def evaluated_copy(evaluated, tmp_path) -> EvaluatedPart:
    """A copy of `evaluated` (its database and files), for tests that change it."""
    data_dir = tmp_path / "evaluated"
    shutil.copytree(evaluated.config.data_dir, data_dir)
    config = AppConfig(data_dir=data_dir)
    database = DatabaseClient(config.db)
    yield dataclasses.replace(evaluated, config=config, db=database)
    database.close()


@pytest.fixture
def evaluated_client(evaluated, cad):
    """The API over the evaluated part's database, for read-only route tests."""
    app.dependency_overrides = {get_config: lambda: evaluated.config, get_db: lambda: evaluated.db, get_cad: lambda: cad}
    yield TestClient(app)
    app.dependency_overrides = {}


@pytest.fixture
def evaluated_copy_client(evaluated_copy, cad, spawned):
    """The API over a copy of the evaluated part's database, for route tests that change it."""
    app.dependency_overrides = {
        get_config: lambda: evaluated_copy.config,
        get_db: lambda: evaluated_copy.db,
        get_cad: lambda: cad,
        get_compute: lambda: {},
    }
    yield TestClient(app)
    app.dependency_overrides = {}


@dataclass(frozen=True)
class IsaacJob:
    config: AppConfig
    db: DatabaseClient
    job_id: str


@pytest.fixture
def isaac_job(finished_job, tmp_path) -> IsaacJob:
    """A copy of the finished vial-cap experiment (its database and outputs), relabelled as run on the Isaac sim, for
    tests that change it (clips)."""
    data_dir = tmp_path / "isaac"
    shutil.copytree(finished_job.config.data_dir, data_dir)
    config = AppConfig(data_dir=data_dir)
    database = DatabaseClient(config.db)
    with database.session() as s:
        s.get(JobRow, finished_job.job_id).sim_backend = "isaac"
    yield IsaacJob(config, database, finished_job.job_id)
    database.close()


class FilmingSim(MockSim):
    """A sim that films by answering a few bytes per view ("<view> mp4"), held or not; or fails with `fail`. Records
    each record() call's arguments in calls."""

    badge = "isaac"

    def __init__(self, held: bool = True, fail: str | None = None):
        self.held, self.fail, self.calls = held, fail, []

    def record(self, part, finger, offset, settings, views):
        self.calls.append((part, finger, offset, settings, views))
        if self.fail:
            raise SimError(self.fail)
        return SimRecording(
            held=self.held,
            in_hand=(0.0, 0.4, 0.0, 1.0, 0.0) if self.held else None,
            held_after_transport=None,
            fps=30,
            frames=147,
            duration_s=4.9,
            videos={view: f"{view} mp4".encode() for view in views},
            sim={"envs": 1, "device": "cpu"},
        )


@pytest.fixture
def filming_sim() -> type[FilmingSim]:
    """FilmingSim, to make with filming_sim(held=..., fail=...)."""
    return FilmingSim
