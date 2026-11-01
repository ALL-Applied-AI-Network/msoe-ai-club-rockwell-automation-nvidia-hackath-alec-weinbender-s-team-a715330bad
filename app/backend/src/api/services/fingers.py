"""Fingers: the finger library, and finger previews for the design-space sliders.

The finger library (api/models/finger_record.py) holds the fingers a factory has: each cell's stock fingers (seeded at
startup), fingers uploaded as CAD, and final designs of generation jobs added to it. Evaluation jobs try them on new
parts. Uploaded fingers are placed in the gripper frame automatically (lowest point at the fingertips, z = 0; the face
nearest the other finger at x = 0; centred across the jaws), optionally mirrored or turned over first; the robotics
engineer confirms the placement on the 3D preview.

Previews (input step 6 of a generation job): the fingers at the two ends of one parameter's range (the others in the
middle), or the fingers of given designs, each with its pieces, grasp settings, closed gap and problems. The geometry
comes from the cell profile's gripper, so a preview shows what this cell would print and simulate.
"""

import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from api.clients.cad import CadClient, UnsupportedCadFormatError
from api.clients.database import DatabaseClient
from api.config import AppConfig
from api.db.tables import FingerRow, QualificationRow, RealSessionRow
from api.models.cell_profile import CellProfileVersion
from api.models.design import Design
from api.models.family import FamilyChoice
from api.models.finger import STOCK_TIP_FRICTION, STOCK_TIP_MM, Finger, build_finger, problems, stock_blade, stock_finger
from api.models.finger_record import FingerFamily, FingerRecord, FingerSource
from api.models.part import Part
from api.models.piece import Piece, hull_piece, pieces_bounds
from api.models.search_space import ParamSummary, SearchSpace
from api.services import cell_profiles
from api.services.cell_profiles import get_profile

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
NUMBER_ATTEMPTS = 5  # tries at the next finger number when another finger takes it at the same moment
MAX_NAME = 200
# The cell's installed fingers have no part number: they're custom aluminium blades with a hooked tip (CONTEXT.md)
STOCK_FINGER_NAME = "Hooked-tip aluminium fingers"
EDITABLE = {"name", "family", "material", "pad_friction", "quantity_on_hand", "notes", "archived"}
PLACEMENT_NOTE = "placed automatically: check on the 3D preview that it sits on the jaw the right way round"


class PreviewError(ValueError):
    """The preview can't be made as asked, e.g. varying a parameter that's locked."""


class FingerNotFoundError(LookupError):
    pass


class FingerInputError(ValueError):
    """A finger that can't be stored or changed as asked: an unreadable file, a blank name, an unknown field."""


class UnsupportedFingerFormatError(ValueError):
    """A file the app doesn't read (a native SolidWorks file, say)."""


class FingerConflictError(ValueError):
    """The design is in the library already, or it can't be added (the stock fingers)."""


@dataclass(frozen=True)
class FingerStats:
    """Where a finger has been tried, from its qualifications."""

    parts_evaluated: int  # parts with a prediction
    best_success: float | None  # its best predicted success on any of them
    validated_parts: int  # parts with real-robot sessions logged


def ensure_stock_fingers(db: DatabaseClient) -> None:
    """Every cell profile name gets one stock finger in the library, if it has none: the cell's installed fingers, tried
    like any other library finger. Run at startup (after the default cell profile is seeded) and when a profile is
    created."""
    for profile in cell_profiles.list_profiles(db):
        with db.session() as s:
            found = s.scalar(select(FingerRow.id).where(FingerRow.source == "stock", FingerRow.cell_profile_name == profile.name).limit(1))
        if found is None:
            _store(
                db,
                name=STOCK_FINGER_NAME,
                source="stock",
                cell_profile_name=profile.name,
                family="stock",
                material="Aluminium, soft tips",
                pad_friction=STOCK_TIP_FRICTION,
                extent_mm=profile.profile.stock_finger_mm,
            )
            logger.info("Finger library: added the stock fingers of %r", profile.name)


def create_finger(
    db: DatabaseClient,
    config: AppConfig,
    cad: CadClient,
    filename: str,
    content: bytes,
    *,
    cell_profile_id: int,
    units: Literal["mm", "in"] | None = None,
    name: str | None = None,
    family: FingerFamily = "other",
    material: str = "PLA",
    pad_friction: tuple[float, float] | None = None,
    quantity_on_hand: int = 0,
    notes: str = "",
    mirror: bool = False,
    upside_down: bool = False,
) -> FingerRecord:
    """Store an uploaded finger (a STEP or STL of one finger): read it, place it in the gripper frame and split it into
    convex pieces. mirror: its gripping face points +x in the file (it's mirrored in x); upside_down: its fingertips
    point up in the file (it's turned over about x). pad_friction defaults to the cell profile's printed pad."""
    filename = Path(filename or "").name  # never a path the client chose
    if not filename:
        raise FingerInputError("the upload has no file name")
    if len(content) > MAX_UPLOAD_BYTES:
        raise FingerInputError(f"{filename}: larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    if Path(filename).suffix.lower() == ".stl" and units is None:
        raise FingerInputError("units required for STL: mm or in")
    if family == "stock":
        raise FingerInputError("the stock fingers are added by the app, one per cell; upload this as another family")
    profile = get_profile(db, cell_profile_id)
    try:
        measured, _ = cad.read_part(filename, content, units or "mm")
    except UnsupportedCadFormatError as e:
        raise UnsupportedFingerFormatError(str(e)) from e
    except ValueError as e:
        raise FingerInputError(str(e)) from e
    pieces = place_in_gripper_frame(measured.pieces, mirror=mirror, upside_down=upside_down)
    lo, hi = pieces_bounds(pieces)
    extent = tuple(float(v) for v in hi - lo)
    finger_id = uuid.uuid4().hex[:12]
    folder = config.uploads_dir / f"finger_{finger_id}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    path.write_bytes(content)
    record = _store(
        db,
        finger_id=finger_id,
        name=_clean(name or "") or Path(filename).stem,
        source="uploaded",
        cell_profile_name=profile.name,
        family=family,
        material=material,
        pad_friction=pad_friction or profile.profile.pad_friction,
        quantity_on_hand=quantity_on_hand,
        notes=notes,
        warnings=_placement_warnings(pieces, profile),
        file_path=str(path),
        extent_mm=extent,
        pieces=pieces,
    )
    logger.info("Finger %s: uploaded %s (%s), %d pieces", record.code, filename, profile.name, len(pieces))
    return record


def place_in_gripper_frame(pieces: list[Piece], *, mirror: bool = False, upside_down: bool = False) -> list[Piece]:
    """A finger's convex pieces as uploaded (the CAD frame, centred, lowest point at z = 0) moved into the gripper frame
    G: optionally turned over about x and mirrored in x first, then the fingertips at z = 0, the face nearest the other
    finger (the smallest x) at x = 0, and centred in y."""
    points = [np.asarray(piece.points, float) for piece in pieces]
    sign = np.array([-1.0 if mirror else 1.0, -1.0 if upside_down else 1.0, -1.0 if upside_down else 1.0])
    points = [p * sign for p in points]
    every = np.vstack(points)
    lo, hi = every.min(axis=0), every.max(axis=0)
    shift = np.array([-lo[0], -(lo[1] + hi[1]) / 2, -lo[2]])
    return [hull_piece(p + shift) for p in points]  # rebuilt hulls: a mirror image would turn the triangles inside out


def _placement_warnings(pieces: list[Piece], profile: CellProfileVersion) -> list[str]:
    g = profile.profile.gripper
    lo, hi = pieces_bounds(pieces)
    out = [PLACEMENT_NOTE]
    free_x, free_y = g.free_space_mm
    if hi[0] + g.stroke_mm > free_x or max(abs(lo[1]), abs(hi[1])) > free_y:
        out.append(
            f"it reaches {hi[0]:.1f} mm out (x) and {max(abs(lo[1]), abs(hi[1])):.1f} mm across (y): more than the {free_x:g} x "
            f"{free_y:g} mm the gripper leaves free, with the jaws open"
        )
    length = float(hi[2] - lo[2])
    if g.max_finger_length_mm is not None and length > g.max_finger_length_mm:
        out.append(f"it's {length:.1f} mm long; the gripper allows {g.max_finger_length_mm:g} mm at the cell's air pressure")
    return out


def add_from_job(db: DatabaseClient, job_id: str, label: str, *, name: str | None = None) -> FingerRecord:
    """Add a final design of a finished generation job (D1, D2, ..., or IMP) to the library, as built for the job's
    part on the job's cell profile version. Raises FingerConflictError for the stock fingers (already in the library)
    and for a design added before."""
    # Imported here: the results service imports the optimizer's models, which this module needn't load at import time.
    from api.services import results

    if label.strip().upper() == "STOCK":
        raise FingerConflictError("the stock fingers are in the library already")
    job, trial = results.final_trial(db, job_id, label)
    label = trial.label  # as the job labels it, whatever case was asked for
    with db.session() as s:
        taken = s.scalar(select(FingerRow).where(FingerRow.origin_job_id == job_id, FingerRow.origin_label == label).limit(1))
        if taken is not None:
            raise FingerConflictError(
                f"{job.experiment_id} {label} is in the library already, as {FingerRecord.model_validate(taken).code}"
            )
    profile = get_profile(db, job.cell_profile_id)
    design = Design(kind=trial.kind, params=trial.params)
    record = _store(
        db,
        name=_clean(name or "") or f"{job.experiment_id} {label} ({job.name})"[:MAX_NAME],
        source="generated",
        cell_profile_name=profile.name,
        family=design.family or "imprint",
        material="PLA",
        pad_friction=profile.profile.pad_friction,
        built_for=job.part,
        design=design,
        cell_profile_id=profile.id,
        origin_job_id=job.id,
        origin_label=label,
        origin_sim_backend=job.sim_backend,
    )
    logger.info("Finger %s: added %s %s to the library", record.code, job.experiment_id, label)
    return record


def get_finger(db: DatabaseClient, finger_id: str) -> FingerRecord:
    with db.session() as s:
        row = s.get(FingerRow, finger_id)
        if row is None:
            raise FingerNotFoundError(finger_id)
        return FingerRecord.model_validate(row)


def list_fingers(
    db: DatabaseClient,
    *,
    cell_profile_name: str | None = None,
    family: FingerFamily | None = None,
    source: FingerSource | None = None,
    archived: bool | None = False,
    part_id: str | None = None,
    min_success: float | None = None,
) -> list[tuple[FingerRecord, FingerStats]]:
    """The library, by finger number, with where each finger has been tried. archived: False (default) leaves archived
    fingers out, True lists only them, None both. part_id: only fingers evaluated on that part; min_success: only
    fingers whose best predicted success reaches it."""
    query = select(FingerRow).order_by(FingerRow.number)
    if cell_profile_name is not None:
        query = query.where(func.lower(FingerRow.cell_profile_name) == cell_profile_name.lower())
    if family is not None:
        query = query.where(FingerRow.family == family)
    if source is not None:
        query = query.where(FingerRow.source == source)
    if archived is not None:
        query = query.where(FingerRow.archived == archived)
    with db.session() as s:
        records = [FingerRecord.model_validate(row) for row in s.scalars(query)]
        quals = list(s.scalars(select(QualificationRow).where(QualificationRow.finger_id.in_([r.id for r in records]))))
        with_sessions = set(
            s.scalars(select(RealSessionRow.qualification_id).where(RealSessionRow.qualification_id.in_([q.id for q in quals])))
        )
    out = []
    for record in records:
        mine = [q for q in quals if q.finger_id == record.id]
        predicted = [q for q in mine if q.prediction is not None]
        if part_id is not None and not any(q.part_id == part_id for q in predicted):
            continue
        best = max((q.prediction.success for q in predicted), default=None)
        if min_success is not None and (best is None or best < min_success):
            continue
        out.append((record, FingerStats(len(predicted), best, sum(1 for q in mine if q.id in with_sessions))))
    return out


def compatible_fingers(db: DatabaseClient, cell_profile_name: str) -> list[FingerRecord]:
    """The fingers an evaluation on this cell tries by default: its stock fingers first, then every other unarchived one
    for the cell, by number."""
    ensure_stock_fingers(db)
    found = [record for record, _ in list_fingers(db, cell_profile_name=cell_profile_name)]
    return sorted(found, key=lambda r: (r.source != "stock", r.number))


def update_finger(db: DatabaseClient, finger_id: str, changes: dict[str, Any]) -> FingerRecord:
    """Apply the fields sent, and only those (PATCH). The geometry and where it came from never change."""
    unknown = set(changes) - EDITABLE
    if unknown:
        raise FingerInputError(f"can't change {', '.join(sorted(unknown))}")
    record = get_finger(db, finger_id)
    values = dict(changes)
    if "name" in values:
        values["name"] = _clean(values["name"] or "")
        if not values["name"]:
            raise FingerInputError("a finger needs a name")
        if len(values["name"]) > MAX_NAME:
            raise FingerInputError(f"names are at most {MAX_NAME} characters")
    if values.get("family") == "stock" and record.source != "stock":
        raise FingerInputError("only the cell's own fingers are the stock fingers")
    if values.get("archived") and record.source == "stock":
        raise FingerInputError("the stock fingers stay in the library: they're on the robot")
    try:
        updated = FingerRecord.model_validate({**record.model_dump(), **values})
    except ValidationError as e:
        raise FingerInputError("; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())) from e
    with db.session() as s:
        row = s.get(FingerRow, finger_id)
        for key in values:
            setattr(row, key, getattr(updated, key))
    logger.info("Finger %s: updated %s", record.code, ", ".join(sorted(values)))
    return updated


def finger_geometry(db: DatabaseClient, finger_id: str) -> tuple[FingerRecord, Finger]:
    """The finger's pieces in the gripper frame, for the 3D preview, on the latest version of its cell's profile (the
    version it was built with, if that's gone). The stock fingers are the twin's model of the real blades (stock_blade):
    jaws closed, built for no part."""
    record = get_finger(db, finger_id)
    gripper = cell_profile_for(db, record).profile.gripper
    if record.source == "stock":
        blade = gripper.blade_mm[2]
        return record, Finger(
            pieces=stock_blade(gripper),
            tip_height_mm=STOCK_TIP_MM,
            jaw_close_mm=0.0,
            contact_mm=blade,
            friction=record.pad_friction,
            closed_gap_mm=0.0,
            jaw_open_mm=gripper.stroke_mm,
            tcp_mm=gripper.tcp_mm,
        )
    return record, record.geometry(gripper)


def cell_profile_for(db: DatabaseClient, record: FingerRecord) -> CellProfileVersion:
    """The latest version of the finger's cell profile; for a generated finger whose profile is gone, the version it was
    built with."""
    try:
        return cell_profiles.list_versions(db, record.cell_profile_name)[-1]
    except cell_profiles.CellProfileNotFoundError:
        if record.cell_profile_id is None:
            raise
        return get_profile(db, record.cell_profile_id)


def _store(db: DatabaseClient, *, finger_id: str | None = None, **values) -> FingerRecord:
    """A new library row with the next free finger number."""
    finger_id = finger_id or uuid.uuid4().hex[:12]
    for attempt in range(1, NUMBER_ATTEMPTS + 1):
        try:
            with db.session() as s:
                number = (s.scalar(select(func.max(FingerRow.number))) or 0) + 1
                row = FingerRow(id=finger_id, number=number, created=time.time(), **values)
                s.add(row)
                s.flush()
                return FingerRecord.model_validate(row)
        except IntegrityError:
            if attempt == NUMBER_ATTEMPTS:
                raise
            logger.warning("Finger library: number taken at the same moment; retrying")
    raise AssertionError("unreachable")


def _clean(name: str) -> str:
    return " ".join(name.split())


@dataclass(frozen=True)
class DesignPreview:
    label: str  # "min" / "max" for a varied parameter, "centre" for the default, the index for given designs
    design: Design
    finger: Finger | None  # None when it couldn't be built (problems says why)
    problems: list[str]


@dataclass(frozen=True)
class FingerPreview:
    designs: list[DesignPreview]
    free: list[str]  # the parameters that would be searched
    params: list[ParamSummary]  # each parameter's ranges, as step 6 shows them


def preview_fingers(
    db: DatabaseClient,
    part: Part,
    cell_profile_id: int,
    choice: FamilyChoice,
    *,
    clearance_mm: float | None = None,
    grip_height_mm: float | None = None,
    vary: str | None = None,
    designs: list[Design] | None = None,
    others: list[Part] | None = None,
) -> FingerPreview:
    """With `vary`: two designs, every free parameter at the middle of the cube except `vary`, at its low and high end.
    With `designs`: those. With neither: the middle design (or the locked one). A grip height locked in step 5 locks the
    tip height here too, as plan_job does. Raises CellProfileNotFoundError for an unknown profile and PreviewError for a
    request that can't be previewed. others: the job's other resting poses' parts, which bound the slack too."""
    if vary is not None and designs is not None:
        raise PreviewError("give vary or designs, not both")
    gripper = get_profile(db, cell_profile_id).profile.gripper
    space = SearchSpace(part, choice.with_grip_height(grip_height_mm), gripper, clearance_mm, others or [])
    if vary is not None:
        labelled = list(zip(("min", "max"), _ends(space, vary), strict=True))
    elif designs is not None:
        labelled = [(str(i), design) for i, design in enumerate(designs)]
    else:
        labelled = [("centre", space.centre())]
    previews = [_preview(label, design, part, space) for label, design in labelled]
    return FingerPreview(designs=previews, free=space.names, params=space.describe())


def _ends(space: SearchSpace, name: str) -> tuple[Design, Design]:
    """The designs at either end of one free parameter, the others at the middle of the cube."""
    if name not in space.names:
        if name in space.locks:
            why = "it's locked"
        elif name in space.applies:
            why = "it doesn't apply to this part"
        else:
            why = f"{space.family.label} has no such parameter"
        raise PreviewError(f"can't vary {name}: {why}; free parameters are {', '.join(space.names) or 'none'}")
    i = space.names.index(name)

    def at(u: float) -> Design:
        unit = [0.5] * len(space.names)
        unit[i] = u
        return space.from_unit(unit)

    return at(0.0), at(1.0)


def _preview(label: str, design: Design, part: Part, space: SearchSpace) -> DesignPreview:
    gripper = space.gripper
    try:
        finger = stock_finger(part, gripper) if design.kind == "stock" else build_finger(part, design, gripper)
    except Exception as e:  # CadQuery raises its own types on degenerate geometry; the preview reports it instead
        logger.warning("Finger preview: design %s can't be built: %s", label, e)
        return DesignPreview(label, design, None, [f"the finger can't be built: {e}"])
    clearance = None if design.kind == "stock" else space.clearance_mm  # the stock fingers are already on the robot
    return DesignPreview(label, design, finger, problems(part, finger, gripper, clearance_mm=clearance))
