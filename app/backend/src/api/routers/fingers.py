"""Fingers: the finger library (register, browse, edit, preview) and finger previews for the design-space sliders of a
generation job (input step 6). Adding a generation job's design to the library is POST
/api/jobs/{id}/designs/{label}/library (routers/jobs.py)."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.dependencies import CadDep, ConfigDep, DbDep
from api.models.design import Design
from api.models.family import FamilyChoice
from api.models.finger import Finger
from api.models.finger_record import FingerFamily, FingerRecord, FingerSource
from api.models.part import Part
from api.models.search_space import ParamSummary
from api.services import fingers
from api.services.cell_profiles import CellProfileNotFoundError

router = APIRouter(prefix="/api/fingers", tags=["fingers"])


class FingerPreviewRequest(BaseModel):
    part: Part  # as the gripper meets it (posed and turned to the grasp axis)
    others: list[Part] = []  # the job's other resting poses (JobPlan.poses after the first): they bound the slack too
    cell_profile_id: int
    choice: FamilyChoice = FamilyChoice()
    clearance_mm: float | None = Field(None, ge=0)  # the part record's clearance on the table, if set
    grip_height_mm: float | None = Field(None, gt=0)  # the grasp's grip height, if locked in step 5
    vary: str | None = None  # a free parameter: preview its low ("min") and high ("max") ends, the others in the middle
    designs: list[Design] | None = Field(None, min_length=1, max_length=8)  # or these designs, labelled by index

    @model_validator(mode="after")
    def _one_kind(self) -> "FingerPreviewRequest":
        if self.vary is not None and self.designs is not None:
            raise ValueError("give vary or designs, not both")
        return self


class DesignPreviewResponse(BaseModel):
    label: str
    design: Design
    finger: Finger | None  # pieces, grasp settings and closed gap; None if it couldn't be built
    problems: list[str]


class FingerPreviewResponse(BaseModel):
    designs: list[DesignPreviewResponse]
    free: list[str]
    params: list[ParamSummary]


@router.post("/preview")
def preview_fingers(request: FingerPreviewRequest, db: DbDep) -> FingerPreviewResponse:
    """The fingers for a family choice: the two ends of one parameter, given designs, or the middle design."""
    try:
        preview = fingers.preview_fingers(
            db,
            request.part,
            request.cell_profile_id,
            request.choice,
            clearance_mm=request.clearance_mm,
            grip_height_mm=request.grip_height_mm,
            vary=request.vary,
            designs=request.designs,
            others=request.others,
        )
    except CellProfileNotFoundError:
        raise HTTPException(404, f"no cell profile {request.cell_profile_id}") from None
    except fingers.PreviewError as e:
        raise HTTPException(422, str(e)) from None
    return FingerPreviewResponse(
        designs=[DesignPreviewResponse(label=d.label, design=d.design, finger=d.finger, problems=d.problems) for d in preview.designs],
        free=preview.free,
        params=preview.params,
    )


# The finger library


class FingerResponse(FingerRecord):
    """A library finger, and where it has been tried. Lists leave out its geometry (pieces, built_for): GET
    /api/fingers/{id} has it, and /geometry has it in the gripper frame for the 3D preview."""

    parts_evaluated: int
    best_success: float | None
    validated_parts: int


class UploadFingerRequest(BaseModel):
    finger_file: UploadFile  # one finger as STEP (.step, .stp) or STL, up to 50 MB; the sim mirrors it for the other jaw
    cell_profile_id: int  # the cell it fits
    units: Literal["mm", "in"] | None = None  # required for an STL
    name: str | None = None  # blank: the file's name
    family: FingerFamily = "other"
    material: str = "PLA"
    pad_friction_static: float | None = Field(None, gt=0)  # both or neither; neither: the cell profile's printed pad
    pad_friction_dynamic: float | None = Field(None, gt=0)
    quantity_on_hand: int = Field(0, ge=0)
    notes: str = ""
    mirror: bool = False  # the gripping face points +x in the file
    upside_down: bool = False  # the fingertips point up in the file

    @model_validator(mode="after")
    def _both_frictions(self) -> "UploadFingerRequest":
        if (self.pad_friction_static is None) != (self.pad_friction_dynamic is None):
            raise ValueError("give both pad_friction_static and pad_friction_dynamic, or neither")
        return self


class UpdateFingerRequest(BaseModel):
    """Only the fields sent change. The geometry, the cell and where the finger came from never do."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=fingers.MAX_NAME)
    family: FingerFamily | None = None
    material: str | None = None
    pad_friction: tuple[float, float] | None = None
    quantity_on_hand: int | None = Field(None, ge=0)
    notes: str | None = None
    archived: bool | None = None


class FingerGeometryResponse(BaseModel):
    finger: FingerResponse
    geometry: Finger  # pieces in the gripper frame, jaws closed; for the stock fingers, the twin's model of the real blades


@router.get("")
def list_fingers(
    db: DbDep,
    cell_profile: str | None = None,
    family: FingerFamily | None = None,
    source: FingerSource | None = None,
    archived: bool | None = False,
    part_id: str | None = None,
    min_success: float | None = None,
) -> list[FingerResponse]:
    """The finger library, by finger code. cell_profile: a cell profile's name. archived: false (default) leaves
    archived fingers out, true lists only them; leave it empty for both. part_id: only fingers evaluated on that part;
    min_success: only fingers whose best predicted success reaches it."""
    found = fingers.list_fingers(
        db, cell_profile_name=cell_profile, family=family, source=source, archived=archived, part_id=part_id, min_success=min_success
    )
    return [_response(record, stats, geometry=False) for record, stats in found]


@router.post("", status_code=201)
async def upload_finger(form: Annotated[UploadFingerRequest, Form()], db: DbDep, config: ConfigDep, cad: CadDep) -> FingerResponse:
    """Register a finger the factory owns, from its CAD: placed in the gripper frame automatically (check the preview).
    415 for a format we don't read, 422 for a file that can't be read or an STL without units, 404 for an unknown cell
    profile."""
    content = await form.finger_file.read(fingers.MAX_UPLOAD_BYTES + 1)
    friction = None if form.pad_friction_static is None else (form.pad_friction_static, form.pad_friction_dynamic)
    with _http_errors():
        record = await run_in_threadpool(
            lambda: fingers.create_finger(
                db,
                config,
                cad,
                form.finger_file.filename or "",
                content,
                cell_profile_id=form.cell_profile_id,
                units=form.units,
                name=form.name,
                family=form.family,
                material=form.material,
                pad_friction=friction,
                quantity_on_hand=form.quantity_on_hand,
                notes=form.notes,
                mirror=form.mirror,
                upside_down=form.upside_down,
            )
        )
    return _response(record, fingers.FingerStats(0, None, 0))


@router.get("/{finger_id}")
def get_finger(finger_id: str, db: DbDep) -> FingerResponse:
    with _http_errors():
        return _response(fingers.get_finger(db, finger_id), _stats(db, finger_id))


@router.patch("/{finger_id}")
def update_finger(finger_id: str, body: UpdateFingerRequest, db: DbDep) -> FingerResponse:
    """Rename, re-family, archive, or change the material, friction, quantity or notes."""
    with _http_errors():
        record = fingers.update_finger(db, finger_id, body.model_dump(exclude_unset=True))
        return _response(record, _stats(db, finger_id))


@router.get("/{finger_id}/geometry")
async def finger_geometry(finger_id: str, db: DbDep) -> FingerGeometryResponse:
    """The finger in the gripper frame (as built for its own part, for a generated finger), for the 3D preview."""
    with _http_errors():
        record, geometry = await run_in_threadpool(fingers.finger_geometry, db, finger_id)
        return FingerGeometryResponse(finger=_response(record, _stats(db, finger_id)), geometry=geometry)


def _stats(db, finger_id: str) -> fingers.FingerStats:
    found = [stats for record, stats in fingers.list_fingers(db, archived=None) if record.id == finger_id]
    return found[0] if found else fingers.FingerStats(0, None, 0)


def _response(record: FingerRecord, stats: fingers.FingerStats, *, geometry: bool = True) -> FingerResponse:
    data = record.model_dump(exclude={"code"})
    if not geometry:
        data |= {"pieces": None, "built_for": None}
    return FingerResponse(
        **data, parts_evaluated=stats.parts_evaluated, best_success=stats.best_success, validated_parts=stats.validated_parts
    )


@contextmanager
def _http_errors() -> Iterator[None]:
    try:
        yield
    except fingers.FingerNotFoundError as e:
        raise HTTPException(404, f"finger {e} not found") from None
    except CellProfileNotFoundError as e:
        raise HTTPException(404, f"cell profile {e} not found") from None
    except fingers.UnsupportedFingerFormatError as e:
        raise HTTPException(415, str(e)) from None
    except fingers.FingerInputError as e:
        raise HTTPException(422, str(e)) from None
    except fingers.FingerConflictError as e:
        raise HTTPException(409, str(e)) from None
