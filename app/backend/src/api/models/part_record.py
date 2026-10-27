"""An uploaded part (input steps 1-2): the CAD file, what it measured, and what the user confirmed about it. Stored, so
a part can be reopened and reused for later experiments. A job snapshots what it needs (api/models/part.py: Part) when
it's created, so editing the record later doesn't change old jobs."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from api.models.material import MATERIALS, Material, Surface, pair_friction
from api.models.part_cad import PartCad
from api.models.resting_pose import RestingPose

MassUnit = Literal["g", "kg", "oz", "lb"]
IntakeStatus = Literal["ready", "needs_properties"]
GRAMS_PER: dict[str, float] = {"g": 1.0, "kg": 1000.0, "oz": 28.349523125, "lb": 453.59237}


class PartRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # read straight from api.db.tables rows

    id: str
    created: float
    name: str  # the uploaded file's name to start with; renamable
    part_number: str | None = None  # the factory's own number for it, if given
    file_path: str
    source: Literal["step", "stl"]
    units: Literal["mm", "in"]  # what the file was in; everything stored is mm
    measured: PartCad
    material: Material | None = None  # unset until the user confirms one (pre-selected from measured.material_hint)
    density_g_cm3: float | None = Field(None, gt=0)  # overrides the material's density; required for "other"
    surface: Surface = "smooth"
    mass_g: float | None = Field(None, gt=0)  # a measured mass the user typed in; None: the computed mass is used
    mass_unit: MassUnit = "g"  # how the UI shows mass; storage is always grams
    fragile: bool = False
    max_grip_force_n: float | None = Field(None, gt=0)
    clearance_mm: float | None = Field(None, ge=0)  # space to the nearest part or tray wall
    pose: RestingPose | None = None  # None until chosen

    @property
    def density(self) -> float | None:
        if self.density_g_cm3 is not None:
            return self.density_g_cm3
        return MATERIALS[self.material].density_g_cm3 if self.material else None

    @property
    def computed_mass_g(self) -> float | None:
        """CAD volume x density, or None while there's no density."""
        return None if self.density is None else self.measured.volume_mm3 / 1000 * self.density

    @property
    def mass_source(self) -> Literal["measured", "computed"] | None:
        if self.mass_g is not None:
            return "measured"
        return "computed" if self.computed_mass_g is not None else None

    @property
    def confirmed_mass_g(self) -> float | None:
        """The mass the sim uses: the measured one if given, else the computed one."""
        return self.mass_g if self.mass_g is not None else self.computed_mass_g

    @property
    def intake_status(self) -> IntakeStatus:
        """ready: it can be evaluated; needs_properties: it has no mass yet (choose a material or enter one)."""
        return "ready" if self.confirmed_mass_g is not None else "needs_properties"

    def friction(self, pad_friction: tuple[float, float]) -> tuple[float, float]:
        """(static, dynamic) against the printed pad."""
        return pair_friction(self.material, self.surface, pad_friction)
