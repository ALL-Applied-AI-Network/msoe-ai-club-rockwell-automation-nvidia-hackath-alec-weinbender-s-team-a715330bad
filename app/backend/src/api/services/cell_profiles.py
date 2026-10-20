"""Cell profiles (input step 4): saved, versioned robot, gripper and cell settings. A default profile ("UWM CSI cell") is
seeded at startup.

Saved versions never change. Editing a profile adds a row with the next version of its name, and a job points at the
exact row it was designed for, so reopening an old job shows the cell it really used. Names are unique ignoring case,
so "UWM CSI cell" and "uwm csi cell" can't become two profiles that look alike in a dropdown.
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from api.clients.database import DatabaseClient
from api.db.tables import CellProfileRow
from api.models.cell_profile import DEFAULT_PROFILE, DEFAULT_PROFILE_NAME, CellProfile, CellProfileVersion

logger = logging.getLogger(__name__)


class CellProfileNotFoundError(LookupError):
    pass


class CellProfileError(ValueError):
    """A profile that can't be saved as asked (a blank name)."""


class CellProfileConflictError(ValueError):
    """The name is taken, or another version of the profile was saved at the same moment."""


def ensure_default_profile(db: DatabaseClient) -> None:
    """Seed DEFAULT_PROFILE as version 1 of DEFAULT_PROFILE_NAME if no profile exists yet."""
    with db.session() as s:
        if s.scalar(select(CellProfileRow.id).limit(1)) is None:
            s.add(CellProfileRow(name=DEFAULT_PROFILE_NAME, version=1, profile=DEFAULT_PROFILE))
            logger.info("Cell profiles: seeded %r", DEFAULT_PROFILE_NAME)


def get_profile(db: DatabaseClient, profile_id: int) -> CellProfileVersion:
    """One saved version, by its id."""
    with db.session() as s:
        row = s.get(CellProfileRow, profile_id)
        if row is None:
            raise CellProfileNotFoundError(profile_id)
        return CellProfileVersion.model_validate(row)


def list_profiles(db: DatabaseClient) -> list[CellProfileVersion]:
    """The latest version of every named profile, by name."""
    latest = select(CellProfileRow.name, func.max(CellProfileRow.version).label("version")).group_by(CellProfileRow.name).subquery()
    query = (
        select(CellProfileRow)
        .join(latest, (CellProfileRow.name == latest.c.name) & (CellProfileRow.version == latest.c.version))
        .order_by(func.lower(CellProfileRow.name))
    )
    with db.session() as s:
        return [CellProfileVersion.model_validate(row) for row in s.scalars(query)]


def list_versions(db: DatabaseClient, profile: int | str) -> list[CellProfileVersion]:
    """Every saved version of one profile, oldest first. `profile` is any of its versions' ids, or its name."""
    with db.session() as s:
        if isinstance(profile, str):
            wanted = _clean(profile).lower()
            name = s.scalar(select(CellProfileRow.name).where(func.lower(CellProfileRow.name) == wanted).limit(1))
        else:
            name = s.scalar(select(CellProfileRow.name).where(CellProfileRow.id == profile))
        if name is None:
            raise CellProfileNotFoundError(profile)
        rows = s.scalars(select(CellProfileRow).where(CellProfileRow.name == name).order_by(CellProfileRow.version))
        return [CellProfileVersion.model_validate(row) for row in rows]


def create_profile(db: DatabaseClient, name: str, profile: CellProfile) -> CellProfileVersion:
    """A new named profile, saved as version 1."""
    name = _clean(name)
    if not name:
        raise CellProfileError("a cell profile needs a name")
    taken = CellProfileConflictError(f"a cell profile named {name!r} already exists; edit it to save a new version")
    try:
        with db.session() as s:
            if s.scalar(select(CellProfileRow.id).where(func.lower(CellProfileRow.name) == name.lower()).limit(1)) is not None:
                raise taken
            row = CellProfileRow(name=name, version=1, profile=profile)
            s.add(row)
            s.flush()
            saved = CellProfileVersion.model_validate(row)
    except IntegrityError as e:  # the same name created at the same moment
        raise taken from e
    logger.info("Cell profiles: created %r (id %d)", saved.name, saved.id)
    return saved


def update_profile(db: DatabaseClient, profile_id: int, profile: CellProfile) -> CellProfileVersion:
    """Save an edit of a profile as a new version: the next version of its name, whichever of its versions profile_id
    is. The edited version is left as it was, since jobs may point at it."""
    name = None
    try:
        with db.session() as s:
            edited = s.get(CellProfileRow, profile_id)
            if edited is None:
                raise CellProfileNotFoundError(profile_id)
            name = edited.name
            latest = s.scalar(select(func.max(CellProfileRow.version)).where(CellProfileRow.name == name))
            row = CellProfileRow(name=name, version=latest + 1, profile=profile)
            s.add(row)
            s.flush()
            saved = CellProfileVersion.model_validate(row)
    except IntegrityError as e:  # another edit took that version number first
        raise CellProfileConflictError(f"another version of {name!r} was saved at the same moment; reload it and save again") from e
    logger.info("Cell profiles: saved %r version %d (id %d, edited from id %d)", saved.name, saved.version, saved.id, profile_id)
    return saved


def _clean(name: str) -> str:
    """A name as it's stored: trimmed, with runs of whitespace as one space."""
    return " ".join(name.split())
