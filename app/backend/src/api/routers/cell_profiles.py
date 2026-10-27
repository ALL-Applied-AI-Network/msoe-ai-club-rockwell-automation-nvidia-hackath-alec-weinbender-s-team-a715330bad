"""Saved, versioned cell profiles (input step 4). Saving an edit (PUT) adds a version and returns it, with its new id:
the job created after the confirm screen points at that exact version, and old versions never change.

Every profile comes back with what the confirm screen needs besides the settings: where the cell differs from the twin
the sim models (twin_mismatches), and the gripper geometry the fingers will be built for (gripper).
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import DbDep
from api.models.cell_profile import CellProfile, CellProfileVersion, Gripper
from api.services import cell_profiles, fingers
from api.services.cell_profiles import CellProfileConflictError, CellProfileError, CellProfileNotFoundError

router = APIRouter(prefix="/api/cell-profiles", tags=["cell profiles"])


class CreateCellProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    profile: CellProfile


class UpdateCellProfileRequest(BaseModel):
    """The edited settings. The name stays; sending back a whole CellProfileResponse works too (the rest is ignored)."""

    profile: CellProfile


class CellProfileResponse(CellProfileVersion):
    twin_mismatches: list[str]  # where the sim's twin differs from this cell, so its results are for another setup
    gripper: Gripper  # what finger geometry and CAD take from this profile

    @classmethod
    def of(cls, saved: CellProfileVersion) -> "CellProfileResponse":
        return cls(**dict(saved), twin_mismatches=saved.profile.twin_mismatches(), gripper=saved.profile.gripper)


@router.get("")
def list_cell_profiles(db: DbDep) -> list[CellProfileResponse]:
    """The latest version of every saved profile."""
    return [CellProfileResponse.of(saved) for saved in cell_profiles.list_profiles(db)]


@router.post("", status_code=201)
def create_cell_profile(req: CreateCellProfileRequest, db: DbDep) -> CellProfileResponse:
    """A new cell; its stock fingers join the finger library."""
    try:
        saved = cell_profiles.create_profile(db, req.name, req.profile)
        fingers.ensure_stock_fingers(db)
        return CellProfileResponse.of(saved)
    except CellProfileConflictError as e:
        raise HTTPException(409, str(e)) from None
    except CellProfileError as e:
        raise HTTPException(422, str(e)) from None


@router.get("/{profile_id}")
def get_cell_profile(profile_id: int, db: DbDep) -> CellProfileResponse:
    try:
        return CellProfileResponse.of(cell_profiles.get_profile(db, profile_id))
    except CellProfileNotFoundError:
        raise HTTPException(404, f"no cell profile with id {profile_id}") from None


@router.put("/{profile_id}")
def update_cell_profile(profile_id: int, req: UpdateCellProfileRequest, db: DbDep) -> CellProfileResponse:
    """Save an edit as the profile's next version, and return that version."""
    try:
        return CellProfileResponse.of(cell_profiles.update_profile(db, profile_id, req.profile))
    except CellProfileNotFoundError:
        raise HTTPException(404, f"no cell profile with id {profile_id}") from None
    except CellProfileConflictError as e:
        raise HTTPException(409, str(e)) from None


@router.get("/{profile_id}/versions")
def list_cell_profile_versions(profile_id: int, db: DbDep) -> list[CellProfileResponse]:
    """Every saved version of the profile this id belongs to, oldest first."""
    try:
        return [CellProfileResponse.of(saved) for saved in cell_profiles.list_versions(db, profile_id)]
    except CellProfileNotFoundError:
        raise HTTPException(404, f"no cell profile with id {profile_id}") from None
