"""Uploaded parts (input steps 1, 2 and 5): store a CAD file and what it measured, confirm material, mass and resting
pose, and propose or check grasp axes.

Each part keeps its file and its surface mesh (mesh.npz: vertices and triangles in the CAD frame, mm) together under
uploads/part_<id>/, and its record (api/models/part_record.py) in the parts table. The convex pieces are split once, at
upload, in the CAD frame; poses and grasp axes only move them. CAD work (reading the file, stable poses, grasp sweeps)
runs outside database sessions, so a slow file never holds one open.
"""

import logging
import uuid
from pathlib import Path
from typing import Any, Literal

import numpy as np
import trimesh
from pydantic import ValidationError
from sqlalchemy import select

from api.clients.cad import CadClient, UnsupportedCadFormatError
from api.clients.database import DatabaseClient
from api.config import AppConfig
from api.db.tables import PartRow
from api.models import grasp
from api.models.cell_profile import CellProfile
from api.models.grasp import GraspCandidate, GraspPick, GraspProposals
from api.models.part_cad import PartMesh
from api.models.part_record import PartRecord
from api.models.resting_pose import AS_AUTHORED, IDENTITY, RestingPose
from api.models.resting_pose import resting_poses as stable_poses

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MESH_FILE = "mesh.npz"
EDITABLE = {"material", "density_g_cm3", "surface", "mass_g", "mass_unit", "fragile", "max_grip_force_n", "clearance_mm", "pose"}

PoseChoice = int | Literal["as_authored"]  # an index into resting_poses(), or the CAD file's own orientation


class PartFileError(ValueError):
    """The file isn't a STEP or STL the CAD kernel can read, or holds no solid."""


class UnsupportedPartFormatError(ValueError):
    """A file format the app doesn't read (a native SolidWorks file, say). The message says what to send instead."""


class PartNotFoundError(LookupError):
    pass


class PartInputError(ValueError):
    """A request the part can't take: an unknown pose index, a value out of range, "other" without a density, or a
    manual grasp that doesn't set a direction (a pick on a top face, say)."""


class PoseNotChosenError(RuntimeError):
    """The grasp step works in the table frame, so it needs the resting pose chosen first."""


def create_part(
    db: DatabaseClient, config: AppConfig, cad: CadClient, filename: str, content: bytes, units: Literal["mm", "in"] | None
) -> PartRecord:
    """Read, measure and store an uploaded STEP or STL. An STL needs its units (STEP files carry their own). The material
    starts as whatever the file names, if anything."""
    name = Path(filename or "").name  # never a path the client chose
    if not name:
        raise PartFileError("the upload has no file name")
    if len(content) > MAX_UPLOAD_BYTES:
        raise PartFileError(f"{name}: larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    if Path(name).suffix.lower() == ".stl" and units is None:
        raise PartFileError("units required for STL: mm or in")
    try:
        measured, mesh = cad.read_part(name, content, units or "mm")
    except UnsupportedCadFormatError as e:
        raise UnsupportedPartFormatError(str(e)) from e
    except ValueError as e:
        raise PartFileError(str(e)) from e
    part_id = uuid.uuid4().hex[:12]
    folder = config.uploads_dir / f"part_{part_id}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(content)
    np.savez_compressed(folder / MESH_FILE, vertices=mesh.vertices, triangles=mesh.triangles)
    with db.session() as s:
        row = PartRow(
            id=part_id,
            name=name,
            file_path=str(path),
            source=measured.source,
            units=(units or "mm") if measured.source == "stl" else "mm",
            measured=measured,
            material=measured.material_hint,
        )
        s.add(row)
        s.flush()
        record = PartRecord.model_validate(row)
    logger.info("Part %s: %s, %s, %d pieces", part_id, name, measured.fit, len(measured.pieces))
    return record


def list_parts(db: DatabaseClient) -> list[PartRecord]:
    """Every stored part, newest first."""
    with db.session() as s:
        return [PartRecord.model_validate(row) for row in s.scalars(select(PartRow).order_by(PartRow.created.desc()))]


def get_part(db: DatabaseClient, part_id: str) -> PartRecord:
    with db.session() as s:
        row = s.get(PartRow, part_id)
        if row is None:
            raise PartNotFoundError(part_id)
        return PartRecord.model_validate(row)


def load_mesh(record: PartRecord) -> PartMesh:
    """The part's surface mesh in the CAD frame, as stored next to its file at upload."""
    with np.load(Path(record.file_path).parent / MESH_FILE) as data:
        return PartMesh(data["vertices"], data["triangles"])


def update_part(db: DatabaseClient, part_id: str, changes: dict[str, Any]) -> PartRecord:
    """Apply the fields sent, and only those (PATCH). mass_g None means "use the computed mass". pose is an index into
    resting_poses() or "as_authored"; the chosen RestingPose itself is stored. Material "other" needs a density. A new
    material doesn't clear an earlier density: send density_g_cm3 None for the material's own."""
    unknown = set(changes) - EDITABLE
    if unknown:
        raise PartInputError(f"can't change {', '.join(sorted(unknown))}")
    record = get_part(db, part_id)
    values = dict(changes)
    if "pose" in values and values["pose"] is not None:
        values["pose"] = _chosen_pose(record, values["pose"])
    try:
        updated = PartRecord.model_validate({**record.model_dump(), **values})
    except ValidationError as e:
        raise PartInputError("; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())) from e
    if updated.material == "other" and updated.density_g_cm3 is None:
        raise PartInputError('material "other" needs density_g_cm3')
    with db.session() as s:
        row = s.get(PartRow, part_id)
        if row is None:
            raise PartNotFoundError(part_id)
        for key in values:
            setattr(row, key, getattr(updated, key))
    logger.info("Part %s: updated %s", part_id, ", ".join(sorted(values)))
    return updated


def resting_poses(db: DatabaseClient, part_id: str) -> list[RestingPose]:
    """The top 4 distinct stable poses, most likely first, then "as in the CAD file". The same part always gives the
    same list, so PATCH's pose index refers to it."""
    record = get_part(db, part_id)
    return stable_poses(load_mesh(record), record.measured.centre_of_mass_mm)


def mesh_stl(db: DatabaseClient, part_id: str, pose: PoseChoice | None = None) -> bytes:
    """The part as a binary STL in the table frame of `pose` (default: the chosen pose, or as authored while none is)."""
    record = get_part(db, part_id)
    mesh = load_mesh(record)
    chosen = _chosen_pose(record, pose, mesh) if pose is not None else record.pose
    table, _ = grasp.table_mesh(record, mesh, chosen)
    return trimesh.Trimesh(table.vertices, table.triangles, process=False).export(file_type="stl")


def propose_grasps(db: DatabaseClient, part_id: str, profile: CellProfile) -> GraspProposals:
    """Auto grasp proposals for the part in its chosen pose, on this cell's gripper."""
    record, mesh, com = _posed(db, part_id)
    return grasp.propose_grasps(mesh, com, record.friction(profile.pad_friction)[0], profile.gripper)


def check_grasp(
    db: DatabaseClient,
    part_id: str,
    profile: CellProfile,
    *,
    angle_deg: float | None = None,
    picks: list[GraspPick] = (),
    grip_height_mm: float | None = None,
) -> GraspCandidate:
    """A manual grasp (an angle, or one or two face picks in the table frame), checked like a proposal."""
    record, mesh, com = _posed(db, part_id)
    try:
        return grasp.check_grasp(
            mesh,
            com,
            record.friction(profile.pad_friction)[0],
            profile.gripper,
            angle_deg=angle_deg,
            picks=picks,
            grip_height_mm=grip_height_mm,
        )
    except ValueError as e:
        raise PartInputError(str(e)) from e


def _posed(db: DatabaseClient, part_id: str) -> tuple[PartRecord, PartMesh, tuple[float, float, float]]:
    record = get_part(db, part_id)
    if record.pose is None:
        raise PoseNotChosenError("choose a resting pose first")
    mesh, com = grasp.table_mesh(record, load_mesh(record))
    return record, mesh, com


def _chosen_pose(record: PartRecord, choice: PoseChoice, mesh: PartMesh | None = None) -> RestingPose:
    if choice == "as_authored":
        return RestingPose(rotation=IDENTITY, label=AS_AUTHORED, source="as_authored", extent_mm=record.measured.extent_mm)
    poses = stable_poses(mesh if mesh is not None else load_mesh(record), record.measured.centre_of_mass_mm)
    if not isinstance(choice, int) or isinstance(choice, bool) or not 0 <= choice < len(poses):
        raise PartInputError(f'pose must be an index from 0 to {len(poses) - 1}, or "as_authored"')
    return poses[choice]
