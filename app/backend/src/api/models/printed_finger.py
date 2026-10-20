"""A finger that was actually printed, so the one on the bench can be matched to its prediction. Its ID is engraved on
it: <experiment ID>-<design label>-<side>, e.g. EXP-0042-D1-L."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

Side = Literal["L", "R", "pair"]


def finger_id(experiment_id: str, design_label: str, side: str | None = None) -> str:
    """EXP-0042-D1 for a pair, EXP-0042-D1-L for one side."""
    base = f"{experiment_id}-{design_label}"
    return base if side in (None, "pair") else f"{base}-{side}"


class PrintedFinger(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # read straight from api.db.tables rows

    id: int
    job_id: str
    finger_id: str
    design_label: str
    side: Side = "pair"
    material: str  # e.g. "PLA", "PETG": should match the friction the sim assumed
    print_date: str | None = None  # ISO date
    notes: str = ""
    created: float


class PrintSelection(BaseModel):
    """Which of an experiment's designs go to the printer and onto the robot. The baselines are always tested: STOCK on
    the aluminium fingers already fitted, IMP printed like the chosen designs."""

    designs: list[str]  # the chosen labels (Job.print_designs), in the order chosen
    printed: list[str]  # what to print: the chosen designs, then IMP
    tested: list[str]  # what a new test plan covers: the chosen designs, then IMP and STOCK
    available: list[str]  # every label of the final test: D1, D2, ..., IMP, STOCK
