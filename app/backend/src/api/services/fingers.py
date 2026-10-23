"""Finger previews for the design-space sliders (input step 6): the fingers at the two ends of one parameter's range (the
others in the middle), or the fingers of given designs, each with its pieces, grasp settings, closed gap and problems.

The geometry comes from the cell profile's gripper, so a preview shows what this cell would print and simulate.
"""

import logging
from dataclasses import dataclass

from api.clients.database import DatabaseClient
from api.models.design import Design
from api.models.family import FamilyChoice
from api.models.finger import Finger, build_finger, problems, stock_finger
from api.models.part import Part
from api.models.search_space import ParamSummary, SearchSpace
from api.services.cell_profiles import get_profile

logger = logging.getLogger(__name__)


class PreviewError(ValueError):
    """The preview can't be made as asked, e.g. varying a parameter that's locked."""


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
