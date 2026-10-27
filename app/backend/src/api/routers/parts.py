"""The parts library (input steps 1, 2 and 5): upload one part or many, confirm material, mass and pose, propose and
check grasps.

Lists leave out each part's convex pieces (measured.pieces is [] and n_pieces says how many there are): they run to tens
of kB a part, and only the 3D preview needs them. GET /api/parts/{id} has them.

friction_vs_pad is for the cell profile named by ?cell_profile_id=, or the default pad (0.6 / 0.5) without one.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from api.clients.database import DatabaseClient
from api.dependencies import CadDep, ConfigDep, DbDep
from api.models.cell_profile import DEFAULT_PROFILE, CellProfile
from api.models.grasp import GraspCandidate, GraspChoice, GraspPick, GraspProposals
from api.models.material import Material, Surface
from api.models.part_record import IntakeStatus, MassUnit, PartRecord
from api.models.resting_pose import RestingPose, is_likely, is_same_pose
from api.services import cell_profiles, parts

router = APIRouter(prefix="/api/parts", tags=["parts"])


class UploadPartRequest(BaseModel):
    part_file: UploadFile  # .step, .stp or .stl, up to 50 MB
    units: Literal["mm", "in"] | None = None  # required for an STL; a STEP carries its own


class UploadPartsRequest(BaseModel):
    """Many files at once: several picked, or every file of a folder (anything that isn't STEP or STL is skipped)."""

    files: list[UploadFile]
    units: Literal["mm", "in"] | None = None  # for every STL among them


class PartResponse(PartRecord):
    """The record plus what follows from it. extent_mm is the CAD file's bounding box as authored (x, y, z in mm): show
    it, so a units mistake is caught at upload."""

    friction_vs_pad: tuple[float, float]  # (static, dynamic) against the printed pad
    n_pieces: int  # convex pieces the part was split into (the list itself is left out of list responses)

    @computed_field
    @property
    def extent_mm(self) -> tuple[float, float, float]:
        return self.measured.extent_mm

    @computed_field
    @property
    def density(self) -> float | None:
        """g/cm3: the entered density, else the material's."""
        return super().density

    @computed_field
    @property
    def computed_mass_g(self) -> float | None:
        return super().computed_mass_g

    @computed_field
    @property
    def mass_source(self) -> Literal["measured", "computed"] | None:
        return super().mass_source

    @computed_field
    @property
    def confirmed_mass_g(self) -> float | None:
        """The mass the sim uses: the measured one if given, else the computed one."""
        return super().confirmed_mass_g

    @computed_field
    @property
    def intake_status(self) -> IntakeStatus:
        """ready: it can be evaluated; needs_properties: choose its material or enter a mass first."""
        return super().intake_status


class IntakeResponse(BaseModel):
    """One file of a bulk upload: ready or needs_properties (stored, with its part), file_error or skipped (not stored)."""

    filename: str
    status: Literal["ready", "needs_properties", "file_error", "skipped"]
    part: PartResponse | None = None
    reason: str | None = None


class UpdatePartRequest(BaseModel):
    """Only the fields sent change. mass_g null means "use the computed mass"; density_g_cm3 null, the material's own.
    pose: an index into GET /poses, or "as_authored". part_number null clears it."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=parts.MAX_NAME)
    part_number: str | None = Field(None, max_length=parts.MAX_NAME)
    material: Material | None = None
    density_g_cm3: float | None = Field(None, gt=0)
    surface: Surface | None = None
    mass_g: float | None = Field(None, gt=0)  # grams, whatever mass_unit the UI shows
    mass_unit: MassUnit | None = None
    fragile: bool | None = None
    max_grip_force_n: float | None = Field(None, gt=0)
    clearance_mm: float | None = Field(None, ge=0)
    pose: Annotated[int, Field(ge=0, strict=True)] | Literal["as_authored"] | None = None

    @model_validator(mode="after")
    def _no_null_for_required_fields(self) -> "UpdatePartRequest":
        required = ("name", "surface", "mass_unit", "fragile")
        nulls = [name for name in required if name in self.model_fields_set and getattr(self, name) is None]
        if nulls:
            raise ValueError(f"{', '.join(nulls)} can't be null")
        return self


PoseParam = Annotated[int, Field(ge=0, strict=True)] | Literal["as_authored"]  # an index into GET /poses


class PoseResponse(RestingPose):
    index: int  # what PATCH /api/parts/{id} and a job spec's poses take as pose
    chosen: bool  # the part record's chosen pose
    likely: bool  # a stable pose at least POSE_CUTOFF likely (GET /api/meta: pose_cutoff): ticked by default in step 2


class ProposeGraspsRequest(BaseModel):
    cell_profile_id: int
    pose: PoseParam | None = None  # the resting pose to propose for; None: the part's chosen pose


class CheckGraspRequest(BaseModel):
    """An angle, or one or two face picks (table frame of the pose, from the 3D view), not both."""

    cell_profile_id: int
    pose: PoseParam | None = None  # the resting pose the grasp is for; None: the part's chosen pose
    angle_deg: float | None = None
    picks: list[GraspPick] = Field(default_factory=list, max_length=2)
    grip_height_mm: float | None = Field(None, gt=0)  # fingertips this far up; locks tip_height_mm in every family
    # A section grasp chosen before (a proposal's centre_mm and span_mm, with its angle): checked on that same section
    centre_mm: tuple[float, float] | None = None
    span_mm: tuple[float, float] | None = None


class CheckGraspResponse(GraspCandidate):
    choice: GraspChoice  # what goes in the job spec if this grasp is accepted


@router.post("", status_code=201)
async def upload_part(form: Annotated[UploadPartRequest, Form()], db: DbDep, config: ConfigDep, cad: CadDep) -> PartResponse:
    """Step 1: store and measure a STEP or STL. 415 for a format we don't read (SolidWorks files say how to export a
    STEP), 422 for a file that can't be read or an STL without units."""
    content = await form.part_file.read(parts.MAX_UPLOAD_BYTES + 1)  # one byte over is enough to refuse it
    with _http_errors():
        record = await run_in_threadpool(parts.create_part, db, config, cad, form.part_file.filename or "", content, form.units)
    return _response(record, DEFAULT_PROFILE)


@router.post("/batch", status_code=201)
async def upload_parts(form: Annotated[UploadPartsRequest, Form()], db: DbDep, config: ConfigDep, cad: CadDep) -> list[IntakeResponse]:
    """Store many STEP or STL files at once, each on its own: one row per file, in the order sent. A file that can't be
    read doesn't stop the others. 422 for more than 50 CAD files."""
    files = [(upload.filename or "", await upload.read(parts.MAX_UPLOAD_BYTES + 1)) for upload in form.files]
    with _http_errors():
        intakes = await run_in_threadpool(parts.create_parts, db, config, cad, files, form.units)
    return [
        IntakeResponse(
            filename=i.filename,
            status=i.status,
            part=_response(i.part, DEFAULT_PROFILE, pieces=False) if i.part is not None else None,
            reason=i.reason,
        )
        for i in intakes
    ]


@router.get("")
def list_parts(db: DbDep, cell_profile_id: int | None = None) -> list[PartResponse]:
    """Every stored part, newest first, without its convex pieces."""
    with _http_errors():
        profile = _profile(db, cell_profile_id)
        return [_response(record, profile, pieces=False) for record in parts.list_parts(db)]


@router.get("/{part_id}")
def get_part(part_id: str, db: DbDep, cell_profile_id: int | None = None) -> PartResponse:
    with _http_errors():
        profile = _profile(db, cell_profile_id)
        return _response(parts.get_part(db, part_id), profile)


@router.patch("/{part_id}")
async def update_part(part_id: str, body: UpdatePartRequest, db: DbDep, cell_profile_id: int | None = None) -> PartResponse:
    """Steps 1-2: material, density, surface, mass, handling and the resting pose."""
    with _http_errors():
        profile = _profile(db, cell_profile_id)
        record = await run_in_threadpool(parts.update_part, db, part_id, body.model_dump(exclude_unset=True))
    return _response(record, profile)


@router.get("/{part_id}/poses")
async def resting_poses(part_id: str, db: DbDep) -> list[PoseResponse]:
    """Step 2: the top 4 stable poses, most likely first, then "as in the CAD file"."""
    with _http_errors():
        record = parts.get_part(db, part_id)
        poses = await run_in_threadpool(parts.resting_poses, db, part_id)
    return [
        PoseResponse(**pose.model_dump(), index=i, chosen=is_same_pose(pose, record.pose), likely=is_likely(pose))
        for i, pose in enumerate(poses)
    ]


@router.get("/{part_id}/mesh", response_class=Response, responses={200: {"content": {"model/stl": {}}}})
async def part_mesh(part_id: str, db: DbDep, pose: str | None = None) -> Response:
    """Steps 2 and 5: the part as a binary STL in the table frame. pose: an index into /poses, "as_authored", or none
    for the chosen pose (as authored while none is chosen)."""
    if pose is not None and pose != "as_authored" and not pose.isdigit():
        raise HTTPException(422, 'pose must be an index into /poses, or "as_authored"')
    choice = int(pose) if pose is not None and pose.isdigit() else pose
    with _http_errors():
        data = await run_in_threadpool(parts.mesh_stl, db, part_id, choice)
    return Response(data, media_type="model/stl", headers={"Content-Disposition": f'inline; filename="part_{part_id}.stl"'})


@router.post("/{part_id}/grasps")
async def propose_grasps(part_id: str, body: ProposeGraspsRequest, db: DbDep) -> GraspProposals:
    """Step 5: up to 3 grasp axes for the part in a resting pose (by default its chosen one), on the profile's gripper;
    or why nothing fits."""
    with _http_errors():
        profile = _profile(db, body.cell_profile_id)
        return await run_in_threadpool(parts.propose_grasps, db, part_id, profile, body.pose)


@router.post("/{part_id}/grasps/check")
async def check_grasp(part_id: str, body: CheckGraspRequest, db: DbDep) -> CheckGraspResponse:
    """Step 5: a manual grasp checked by geometry: blocked, warn or ok, with reasons."""
    with _http_errors():
        profile = _profile(db, body.cell_profile_id)
        candidate = await run_in_threadpool(
            lambda: parts.check_grasp(
                db,
                part_id,
                profile,
                angle_deg=body.angle_deg,
                picks=body.picks,
                grip_height_mm=body.grip_height_mm,
                pose=body.pose,
                centre_mm=body.centre_mm,
                span_mm=body.span_mm,
            )
        )
    choice = GraspChoice(
        angle_deg=candidate.angle_deg,
        centre_mm=candidate.centre_mm,
        span_mm=candidate.span_mm,
        source="manual",
        grip_height_mm=body.grip_height_mm,
        picks=body.picks,
    )
    return CheckGraspResponse(**candidate.model_dump(), choice=choice)


def _profile(db: DatabaseClient, profile_id: int | None) -> CellProfile:
    return DEFAULT_PROFILE if profile_id is None else cell_profiles.get_profile(db, profile_id).profile


def _response(record: PartRecord, profile: CellProfile, *, pieces: bool = True) -> PartResponse:
    data = record.model_dump()
    if not pieces:
        data["measured"]["pieces"] = []
    return PartResponse(**data, friction_vs_pad=record.friction(profile.pad_friction), n_pieces=len(record.measured.pieces))


@contextmanager
def _http_errors() -> Iterator[None]:
    """The parts and profile services' errors as HTTP statuses."""
    try:
        yield
    except parts.PartNotFoundError as e:
        raise HTTPException(404, f"part {e} not found") from None
    except cell_profiles.CellProfileNotFoundError as e:
        raise HTTPException(404, f"cell profile {e} not found") from None
    except parts.PoseNotChosenError as e:
        raise HTTPException(409, str(e)) from None
    except parts.UnsupportedPartFormatError as e:
        raise HTTPException(415, str(e)) from None
    except (parts.PartFileError, parts.PartInputError) as e:
        raise HTTPException(422, str(e)) from None
