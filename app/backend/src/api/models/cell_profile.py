"""The cell profile ("workcell"): the robot, gripper and cell settings a job is designed for (input step 4). Saved in
Settings and versioned: editing a profile makes a new version, and a job points at the exact version it used.

The profile drives the finger geometry and CAD (stroke, free space, mount features, hole clearance) through `gripper`.
The sim, though, always models the twin's SMC MHZL2-16D2 cell: twin_mismatches() says where a profile differs from it,
so a job never silently assumes the twin is another gripper.

Values marked in `to_confirm` are placeholders until measured at the cell (CONTEXT.md, open questions).
"""

import math
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.models.error_model import ErrorModel


class MountHole(BaseModel):
    """A screw hole for the mount. On a +y or -y mount face it goes through the blade's thickness (along y); on the +x
    face it goes into the blade along x, from the face the jaw sits against (see FingerMount)."""

    below_root_mm: float  # down from the blade's root (its top end, where it meets the jaw)
    x_mm: float = 6.0  # +y / -y faces: across the blade, from its inner face (x = 0)
    y_mm: float = 0.0  # +x face: across the blade's thickness, from its mid-plane
    diameter_mm: float = Field(3.2, gt=0)  # nominal; hole_clearance_mm is added when printing
    depth_mm: float | None = Field(None, gt=0)  # +x face: how deep it goes in from the jaw's face; None: through the blade
    counterbore_diameter_mm: float | None = 5.2  # None: no counterbore
    counterbore_depth_mm: float = 1.0  # +y / -y: from each face; +x: from the inner face, for a through hole


class LocatingFeature(BaseModel):
    """A locating pin (a boss standing out of the mount face) or slot (cut into it), keying the finger to the jaw."""

    kind: Literal["pin", "slot"]
    below_root_mm: float
    x_mm: float
    diameter_mm: float = Field(gt=0)  # a slot's width
    length_mm: float = 0.0  # a slot's length along the blade
    height_mm: float = Field(1.0, gt=0)  # how far a pin stands out, or how deep a slot is


class FingerMount(BaseModel):
    """How a finger bolts to the jaw, in one of two ways:

    - face "+x": the jaw is a flat tongue beside the blade's root, on its outer side (away from the other finger), as on
      SMC's MHZL2-16D2. The root is cut back to the tongue's inner face, face_x_mm from the blade's inner face with the
      jaws closed, for jaw_length_mm below the root plus jaw_clearance_mm, so the tongue seats against that face and
      its end clears the step. Screws come through the tongue into the blade along x.
    - face "+y" or "-y": the blade bolts flat to the jaw by that face, with screws through its thickness (along y).

    The defaults are SMC_FLAT_JAW_MOUNT, from SMC's STEP of the gripper (cad/SMC-MHZL2-16D2.step). PHOTO_MOUNT is the
    twin's photo reconstruction, which the STEP's jaw contradicts. Measure the real jaw before printing."""

    face: Literal["+x", "+y", "-y"] = "+x"  # the blade face that sits against the jaw
    face_x_mm: float = Field(7.45, gt=0)  # +x: where the jaw's face is, along x from the blade's inner face, jaws closed
    jaw_length_mm: float = Field(15.0, gt=0)  # +x: how far the jaw reaches down the blade from its root
    jaw_clearance_mm: float = Field(0.5, ge=0)  # +x: room left below the jaw's end
    face_size_mm: tuple[float, float] | None = (8.0, 15.0)  # the jaw's mounting face: width x length
    # +x: M3 screws through the tongue's 3.4 mm holes, self-tapping into the printed root (M3 x 10: 5 mm of tongue, 5 in)
    holes: list[MountHole] = [
        MountHole(below_root_mm=4.0, diameter_mm=2.5, depth_mm=6.0, counterbore_diameter_mm=None),
        MountHole(below_root_mm=11.0, diameter_mm=2.5, depth_mm=6.0, counterbore_diameter_mm=None),
    ]
    locating: list[LocatingFeature] = []  # +y and -y faces only

    @model_validator(mode="after")
    def _features_fit_the_face(self) -> "FingerMount":
        if self.face != "+x":
            if any(hole.depth_mm is not None for hole in self.holes):
                raise ValueError("holes through the blade's thickness (a +y or -y mount face) have no depth: they go through")
            return self
        if self.locating:
            raise ValueError("locating pins and slots are only modelled on a +y or -y mount face")
        for i, hole in enumerate(self.holes, 1):
            if hole.below_root_mm + hole.diameter_mm / 2 > self.jaw_length_mm + self.jaw_clearance_mm:
                raise ValueError(f"mount hole {i} reaches past the end of the jaw ({self.jaw_length_mm:g} mm below the root)")
            if hole.depth_mm is not None and hole.counterbore_diameter_mm:
                raise ValueError(f"mount hole {i} is blind, so it can't have a counterbore on the blade's inner face")
        return self

    def describe(self) -> str:
        """The mount in words, for the print sheet."""
        below = " and ".join(f"{hole.below_root_mm:g}" for hole in self.holes) or "no"
        if self.face != "+x":
            return f"screws through the blade's thickness, {below} mm below the root, its {self.face} face against the jaw"
        cut = self.jaw_length_mm + self.jaw_clearance_mm
        return (
            f"screws through the jaw beside the blade's root, into holes {below} mm below the root; the root is cut back "
            f"to {self.face_x_mm:g} mm from the inner face for its top {cut:g} mm"
        )


# SMC's STEP of the MHZL2-16D2 (cad/README.md): each jaw ends in a tongue 5 mm thick along the travel, 8 mm wide and
# 15 mm long, its inner face 7.45 mm from the centreline with the jaws closed, with two 3.4 mm holes along the travel 4
# and 11 mm below the shoulder it stands out of. The blade's root butts against that shoulder.
SMC_FLAT_JAW_MOUNT = FingerMount()
# The twin's photo reconstruction (scene_config.FINGER_MOUNT_HOLES, photo_finger_detail.json): two screws through the
# blade's thickness on its centreline, 10 and 23 mm below its root. The 23 mm hole is past the end of SMC's jaw.
PHOTO_MOUNT = FingerMount(
    face="-y", face_size_mm=None, holes=[MountHole(below_root_mm=10.0, x_mm=6.0), MountHole(below_root_mm=23.0, x_mm=6.0)]
)


def mount_fit_problems(mount: FingerMount, blade_mm: tuple[float, float, float], mount_kept_mm: float) -> list[str]:
    """Where a +x mount doesn't fit the blade it's cut into: the jaw's face must lie inside the blade, the cut-back root
    inside the part kept as stock, and blind holes must stop short of the inner face."""
    if mount.face != "+x":
        return []
    width, reach = blade_mm[0], mount.jaw_length_mm + mount.jaw_clearance_mm
    out = []
    if mount.face_x_mm >= width:
        out.append(f"the jaw's face (x {mount.face_x_mm:g} mm) is outside the {width:g} mm blade")
    if reach > mount_kept_mm:
        out.append(f"the jaw reaches {reach:g} mm down the blade, past the {mount_kept_mm:g} mm kept as stock")
    for i, hole in enumerate(mount.holes, 1):
        if hole.depth_mm is not None and hole.depth_mm >= mount.face_x_mm:
            out.append(f"mount hole {i} ({hole.depth_mm:g} mm deep) goes through the {mount.face_x_mm:g} mm root: make it a through hole")
    return out


class Camera(BaseModel):
    name: str
    width_px: int
    height_px: int


class CellSimSettings(BaseModel):
    """Advanced sim settings, hidden by default. The sim server is started with its own (they need a stage rebuild); a job
    records what the server reports and warns where it differs from these."""

    physics_dt_s: float = Field(1 / 60, gt=0)
    solver_position_iterations: int = Field(16, ge=1)
    solver_velocity_iterations: int = Field(2, ge=0)
    contact_offset_mm: float = Field(0.2, ge=0)
    rest_offset_mm: float = 0.0
    envs: int = Field(64, ge=1)  # parallel environments; sets the batch size

    def differences(self, reported: Mapping[str, Any]) -> list[str]:
        """Where the sim server runs with other settings than these. `reported` is the server's `sim` block (what
        SimClient.describe() returns after a batch), keyed as in SERVER_SIM_KEYS. A setting the server doesn't report
        isn't compared: the mock reports none."""
        out = []
        for field, key in SERVER_SIM_KEYS.items():
            value = reported.get(key)
            if isinstance(value, bool) or not isinstance(value, int | float):
                continue
            ours = getattr(self, field)
            if not math.isclose(value, ours, rel_tol=1e-6, abs_tol=1e-12):
                out.append(f"{field}: this profile asks for {ours:g}, the sim server runs {value:g}")
        return out


# CellSimSettings field -> the key the sim server reports it under in its `sim` block (section 5 of the plan).
SERVER_SIM_KEYS = {
    "physics_dt_s": "physics_dt",
    "solver_position_iterations": "solver_position_iterations",
    "solver_velocity_iterations": "solver_velocity_iterations",
    "contact_offset_mm": "contact_offset_mm",
    "rest_offset_mm": "rest_offset_mm",
    "envs": "envs",
}


class Gripper(BaseModel):
    """What finger geometry and CAD need from the cell, in mm. Defaults are the UWM CSI cell (SMC MHZL2-16D2 and the
    stock aluminium blades)."""

    stroke_mm: float = 6.0  # jaw travel per jaw: 0 closed, stroke open
    blade_mm: tuple[float, float, float] = (12.0, 6.0, 76.0)  # stock blade: width along x, thickness along y, length along z
    mount_kept_mm: float = 30.0  # top of the blade kept as stock, where it's screwed to the jaw
    free_space_mm: tuple[float, float] = (45.0, 30.0)  # how far a finger may reach in |x| (jaws open) and |y|
    pad_friction: tuple[float, float] = (0.6, 0.5)  # printed pad, static and dynamic
    stock_tip_gap_mm: float = 16.0  # the stock hooked tips, jaws fully open
    tcp_mm: float = 293.0
    mount: FingerMount = FingerMount()
    hole_clearance_mm: float = 0.25  # added to every printed hole's diameter (printed holes come out undersized)
    max_finger_length_mm: float | None = None  # the gripper maker's limit at the cell's air pressure; None: unknown

    @model_validator(mode="after")
    def _mount_fits_the_blade(self) -> "Gripper":
        if problems := mount_fit_problems(self.mount, self.blade_mm, self.mount_kept_mm):
            raise ValueError("; ".join(problems))
        return self


class CellProfile(BaseModel):
    robot_model: str = "FANUC ER-4iA"
    tcp_offset_mm: float = 293.0  # J6 to the fingertips
    gripper_model: str = "SMC MHZL2-16D2"
    stroke_per_jaw_mm: float = Field(6.0, gt=0)
    grip_force_n: float | None = Field(None, gt=0)  # per jaw, at the cell's air pressure; None: the twin's jaw drive
    air_pressure_mpa: float | None = Field(None, gt=0)
    finger_mount: FingerMount = FingerMount()
    hole_clearance_mm: float = Field(0.25, ge=0)
    stock_fingers: str = "aluminium blade, 76 × 12 × 6 mm, hooked tip"
    stock_finger_mm: tuple[float, float, float] = (12.0, 6.0, 76.0)  # width, thickness, length
    stock_tip_gap_mm: float = Field(16.0, gt=0)  # between the hooked tips, jaws fully open
    mount_kept_mm: float = Field(30.0, gt=0)
    max_finger_length_mm: float | None = Field(None, gt=0)
    free_space_mm: tuple[float, float] = (45.0, 30.0)  # beside the gripper: |x| with the jaws open, |y|
    approach: Literal["top-down"] = "top-down"
    lift_m: float = Field(0.13, gt=0)
    pad_material: str = "PLA/PETG"
    pad_friction: tuple[float, float] = (0.6, 0.5)  # static, sliding; estimate
    mat_friction: tuple[float, float] | None = None  # table mat; to measure
    cameras: list[Camera] = [
        Camera(name="overhead", width_px=1920, height_px=1080),
        Camera(name="side", width_px=1920, height_px=1080),
        Camera(name="wrist", width_px=1280, height_px=720),
    ]
    sim: CellSimSettings = CellSimSettings()
    # How accurately this cell grasps: how far a grasp may land from where it was aimed (camera, calibration, robot).
    # Copied into each job's spec when the spec leaves its error model unset; a spec may override it.
    grasp_accuracy: ErrorModel = ErrorModel()
    to_confirm: list[str] = []  # fields that are still placeholders

    @model_validator(mode="after")
    def _mount_fits_the_blade(self) -> "CellProfile":
        if problems := mount_fit_problems(self.finger_mount, self.stock_finger_mm, self.mount_kept_mm):
            raise ValueError("; ".join(problems))
        return self

    @property
    def gripper(self) -> Gripper:
        return Gripper(
            stroke_mm=self.stroke_per_jaw_mm,
            blade_mm=self.stock_finger_mm,
            mount_kept_mm=self.mount_kept_mm,
            free_space_mm=self.free_space_mm,
            pad_friction=self.pad_friction,
            stock_tip_gap_mm=self.stock_tip_gap_mm,
            tcp_mm=self.tcp_offset_mm,
            mount=self.finger_mount,
            hole_clearance_mm=self.hole_clearance_mm,
            max_finger_length_mm=self.max_finger_length_mm,
        )

    def twin_mismatches(self) -> list[str]:
        """Where this profile differs from the cell the sim models (the twin's SMC MHZL2-16D2 setup). The fingers are
        built for this profile either way; these say where the sim's answer is for a different cell. The stock blade
        counts because the STOCK baseline runs on the twin's own fingers, not on geometry the app sends."""
        twin = TWIN_CELL
        out = []
        if self.gripper_model != twin.gripper_model:
            out.append(f"the sim models a {twin.gripper_model}, not a {self.gripper_model}")
        for field, unit in (
            ("stroke_per_jaw_mm", "mm"),
            ("tcp_offset_mm", "mm"),
            ("stock_tip_gap_mm", "mm"),
            ("stock_finger_mm", "mm"),
            ("lift_m", "m"),
        ):
            ours, theirs = getattr(self, field), getattr(twin, field)
            if not all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(_values(ours), _values(theirs), strict=True)):
                out.append(f"{field}: this profile has {_show(ours)} {unit}, the sim's twin {_show(theirs)} {unit}")
        return out


class CellProfileVersion(BaseModel):
    """One saved version of a named profile."""

    model_config = ConfigDict(from_attributes=True)  # read straight from api.db.tables rows

    id: int
    name: str
    version: int
    created: float
    profile: CellProfile


def _values(value: float | tuple[float, ...]) -> tuple[float, ...]:
    return value if isinstance(value, tuple) else (value,)


def _show(value: float | tuple[float, ...]) -> str:
    return " × ".join(f"{v:g}" for v in _values(value))


TWIN_CELL = CellProfile()  # what the sim server's twin models
DEFAULT_PROFILE_NAME = "UWM CSI cell"
DEFAULT_PROFILE = CellProfile(
    to_confirm=[
        "gripper_model",  # SMC MHZL2-16D2 or SCHUNK
        "grip_force_n",
        "air_pressure_mpa",
        "finger_mount",
        "hole_clearance_mm",
        "max_finger_length_mm",
        "free_space_mm",
        "pad_friction",
        "mat_friction",
    ]
)
# Earlier built-in defaults: a database whose default profile is still one of these, unedited, gets DEFAULT_PROFILE as
# its next version at startup (services/cell_profiles.py). Until 2026-10-20 the mount was the twin's photo reconstruction.
SUPERSEDED_DEFAULTS = [DEFAULT_PROFILE.model_copy(update={"finger_mount": PHOTO_MOUNT})]
