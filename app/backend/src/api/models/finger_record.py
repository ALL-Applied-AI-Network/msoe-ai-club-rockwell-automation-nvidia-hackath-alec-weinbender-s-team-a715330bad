"""A finger in the finger library: a physical finger the factory has (or could print), reusable across evaluation jobs.

It isn't a design: its geometry is fixed, in the gripper frame G of api/models/finger.py (jaws closed, fingertips at
z = 0, the other finger its mirror image in x), so it can be tried on any part. Three sources:

- stock: the cell's own fingers. The sim server uses its real model of them, so the record has no geometry; the mock
  stands in with finger.stock_finger().
- generated: a final design of a generation job, kept as the part it was built for and its Design, and rebuilt with
  finger.regrip() for each new part: the pad profile stays, the jaws close to where the new part seats against it.
- uploaded: a finger CAD file, placed in G and split into convex pieces like a part (services/fingers.py), and gripping
  a new part through finger.seat().

The finger code (FNG-0001) never changes; the name can.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from api.models.cell_profile import Gripper
from api.models.design import Design
from api.models.finger import STOCK_TIP_MM, Finger, regrip, seat
from api.models.job_spec import SimBackend
from api.models.part import Part
from api.models.piece import Piece

FingerSource = Literal["stock", "generated", "uploaded"]
FingerFamily = Literal["stock", "vpad", "flat", "imprint", "other"]


def finger_code(number: int) -> str:
    return f"FNG-{number:04d}"


class FingerRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # read straight from api.db.tables rows

    id: str  # internal key, used in URLs
    number: int  # fixed for life; finger_code shows it as FNG-0001
    name: str  # renamable
    created: float
    source: FingerSource
    cell_profile_name: str  # the cell (gripper and mount) it fits: evaluations on that cell use it
    family: FingerFamily
    material: str = "PLA"
    pad_friction: tuple[float, float]  # static, dynamic, of its contact surface; the part's friction is scaled from it
    quantity_on_hand: int = Field(0, ge=0)
    notes: str = ""
    archived: bool = False  # left out of new evaluations; past results keep it
    warnings: list[str] = []  # what placing an uploaded finger found (it may reach outside the free space, say)
    # generated
    built_for: Part | None = None  # the part (as the gripper met it) the design was built for
    design: Design | None = None
    cell_profile_id: int | None = None  # the profile version it was built with
    origin_job_id: str | None = None
    origin_label: str | None = None  # D1, D2, ..., IMP
    origin_sim_backend: SimBackend | None = None  # what its generation job ran on: a mock's design is geometry only
    # uploaded
    file_path: str | None = None
    extent_mm: tuple[float, float, float] | None = None
    pieces: list[Piece] | None = None  # in G

    @computed_field
    @property
    def code(self) -> str:
        return finger_code(self.number)

    def grip(self, part: Part, gripper: Gripper, *, tip_height_mm: float | None = None, built: Finger | None = None) -> Finger | None:
        """This finger gripping `part` (posed and turned to a grasp) on this gripper; None for the stock fingers, which
        are the robot's own (the sim gets None for them). tip_height_mm: the grasp's locked grip height, if it has one.
        built: a generated finger's geometry() already built, so its CAD isn't built again for every part."""
        if self.source == "stock":
            return None
        if self.source == "generated":
            finger = regrip(self.built_for, part, self.design, gripper, tip_height_mm=tip_height_mm, built=built)
            return finger.model_copy(update={"friction": self.pad_friction})
        return seat(self.pieces, part, gripper, tip_height_mm=tip_height_mm, friction=self.pad_friction)

    def geometry(self, gripper: Gripper) -> Finger | None:
        """The finger's pieces in G, for the 3D preview: as built for its own part, or as uploaded. None for stock."""
        if self.source == "stock":
            return None
        if self.source == "generated":
            return self.grip(self.built_for, gripper)
        return Finger(
            pieces=self.pieces,
            tip_height_mm=STOCK_TIP_MM,
            jaw_close_mm=0.0,
            contact_mm=0.0,
            friction=self.pad_friction,
            jaw_open_mm=gripper.stroke_mm,
            tcp_mm=gripper.tcp_mm,
        )
