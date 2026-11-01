"""CAD-to-Fingers on the real cell: pick one part, an M6 countersunk screw or the 16 mm cube, off the table and drop it in
the yellow bin, with the grasp aimed at a test-plan offset, so the robot measures what the sim predicted for the same
offset.

This file replaces policy.py in a clone of the organizers' client package
(https://github.com/SIDCLab/PhysicalAI-Hackathon-2026; docs/references/physicalai-client-package.md). See README.md here.

The policy is blind on purpose. Each rollout's prompt (placement.yaml, written by make_placement.py) carries a tag with
the part's and the bin's nominal poses and the offset to command, and optionally how high the fingertips close, e.g.
    Put the screw into the yellow bin. [c2f trial=T0007 dx=+3.00 dy=+0.00 dyaw=+0.0 screw=420,-40,90 bin=480,120,0]
    Put the 16 mm cube into the yellow bin. [c2f trial=T0003 dx=-2.00 dy=+0.00 dyaw=+0.0 cube=420,-40,0 bin=480,120,0 tip=2.5]
A screw is gripped across its shank, near its centre of mass; a cube at its centre, across the faces its yaw points
through. tip= is the fingertips' height above the surface when they close: the height the sim gripped at, so the arm
repeats the sim's grasp (default GRASP_TIP_HEIGHT_MM, the stock rule).
The operator places the part at the nominal pose every rollout, and the policy grasps at that pose plus the offset.
The offset is in the gripper frame of the app's test plans (api/models/test_plan.py): dx along the jaws' closing
direction, dy across it, dyaw about z. So the grasp error is the commanded offset plus however far the operator's
placement is off, the same for every finger design. Without a tag (the mock's instruction), it uses the DEFAULT_* poses
and no offset.

Frames (calibration/FRAMES.md): "tcp" actions are the stock fingertip (UTOOL1) in UF0, mm; x, y are the robot base's,
z_UF0 = z_base - 330 mm, so the surface is at about -335 mm. w, p, r = -180, 0, R points the fingers down and R turns
them about z. Which way the jaws close at a given R isn't documented. The policy measures it: the arm's FK from
obs["joints"] (calibration.geometry.flange_pose, the twin's convention, jaws along the flange's +y) gives the jaw axis,
and obs["tcp_pose"] gives the R it was at. It does this on the first observation and again once it is above the part,
re-aiming before it descends if the jaws are off.

Nothing here was run on the real arm. run.py --mock checks only formats and limits (the mock has no kinematics).
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# --- The cell (FRAMES.md, the client's mock_cell.py, docs/07-cad-models.md) ---------------------------------------------
SURFACE_Z_MM = -335.1  # the work surface in UF0: base z -5.1 mm, minus 330
TCP_BOX_MM = ((150.0, 650.0), (-450.0, 450.0), (-334.0, 300.0))  # what the cell accepts, x, y, z in UF0
REACH_MM = 540.0  # keep targets inside the arm's ~550 mm reach from the base axis
BIN_HEIGHT_MM = 55.0
JAW_AXIS_FLANGE = (0.0, 1.0, 0.0)  # the jaws' travel in the flange frame J6_link (twin: FINGER_SPREAD_AXIS)
TOOL_AXIS_FLANGE = (1.0, 0.0, 0.0)  # the tool's axis in J6_link (twin: TOOL_AXIS)

# --- The task ---------------------------------------------------------------------------------------------------------
DEFAULT_SCREW = (420.0, -40.0, 90.0)  # head x, y (mm) and yaw (deg, head to tip), as placement.yaml gives a screw
DEFAULT_CUBE = (420.0, -40.0, 0.0)  # centre x, y (mm) and yaw (deg, a face's normal), as placement.yaml gives a cube
DEFAULT_BIN = (480.0, 120.0, 0.0)  # centre x, y (mm) and yaw (deg)
GRASP_ALONG_MM = 12.0  # from the screw's head point toward its tip: about its centre of mass (13.4 mm from the head's top)
# Fingertips above the surface when they close, unless the tag sets tip=: below a lying screw's shank axis (3-6 mm), and
# the sim's stock rule for a cube. The cell refuses the TCP below 1.1 mm above the surface (TCP_BOX_MM).
GRASP_TIP_HEIGHT_MM = 2.5
TIP_BELOW_TCP_MM = 0.0  # how far our fingertips end below UTOOL1 (the stock tips); 0 when they keep the stock length
APPROACH_HEIGHT_MM = 60.0  # fingertips above the surface, above the screw
CARRY_HEIGHT_MM = 120.0  # fingertips above the surface while carrying
DROP_ABOVE_BIN_MM = 25.0  # fingertips above the bin's rim when they open
DROP_JAW_YAW_FROM_BIN_DEG = 135.0  # jaws at bin yaw + 135, so the screw (across the jaws) lies along the pocket's diagonal
JAW_YAW_AT_R0_DEG = 90.0  # first guess for the jaws' yaw at R = 0 (at home, FK puts them along base +y), until measured
REAIM_TOLERANCE_DEG = 2.0
MAX_JAW_JUMP_DEG = 20.0  # a later measurement this far from an earlier one is distrusted (joints and tcp_pose out of step)

# --- Motion -----------------------------------------------------------------------------------------------------------
DT_S = 0.1  # each row plays as one 0.1 s step
TRAVEL_STEP_MM = 10.0  # per row: 100 mm/s in free space
FINE_STEP_MM = 3.0  # per row near the table: 30 mm/s
TURN_STEP_DEG = 5.0  # per row, about z
GRIP_DWELL_ROWS = 6  # rows held after closing or opening: 0.6 s for the pneumatic jaws
MAX_CHUNK = 100  # rows per act() call (the cell's limit)

LOG_FILE = Path(__file__).resolve().parent / "cad2fingers_rollouts.jsonl"
TAG = re.compile(
    r"\[c2f\s+trial=(?P<trial>\S+)\s+dx=(?P<dx>[-+0-9.]+)\s+dy=(?P<dy>[-+0-9.]+)\s+dyaw=(?P<dyaw>[-+0-9.]+)"
    r"\s+(?P<kind>screw|cube)=(?P<part>[-+0-9.,]+)\s+bin=(?P<bin>[-+0-9.,]+)(?:\s+tip=(?P<tip>[-+0-9.]+))?\]"
)


@dataclass(frozen=True)
class Rollout:
    """What one rollout's prompt asks for: the part and the bin's nominal poses, the offset to command, and how high the
    fingertips close."""

    trial: str | None
    dx_mm: float
    dy_mm: float
    dyaw_deg: float
    part: tuple[float, float, float]  # a screw's head x, y and yaw (head to tip); a cube's centre x, y and yaw
    bin: tuple[float, float, float]
    kind: str = "screw"  # "screw" or "cube"
    tip_mm: float = GRASP_TIP_HEIGHT_MM


def parse_instruction(text: str | None) -> Rollout:
    """The rollout's tag from obs["trial"]["instruction"], or the defaults with no offset if there is none."""
    match = TAG.search(text or "")
    if match is None:
        return Rollout(None, 0.0, 0.0, 0.0, DEFAULT_SCREW, DEFAULT_BIN)
    part, bin_ = (_pose(match[k]) for k in ("part", "bin"))
    tip = float(match["tip"]) if match["tip"] else GRASP_TIP_HEIGHT_MM
    return Rollout(match["trial"], float(match["dx"]), float(match["dy"]), float(match["dyaw"]), part, bin_, match["kind"], tip)


def _pose(text: str) -> tuple[float, float, float]:
    values = [float(v) for v in text.split(",")]
    if len(values) == 2:
        values.append(0.0)
    if len(values) != 3:
        raise ValueError(f"a pose is x,y or x,y,yaw: {text!r}")
    return values[0], values[1], values[2]


def wrap180(angle: float) -> float:
    """An angle in degrees, in (-180, 180]."""
    a = (angle + 180.0) % 360.0 - 180.0
    return 180.0 if a == -180.0 else a


def nearest_equivalent(angle: float, near: float, period: float = 180.0) -> float:
    """angle + k * period closest to `near`: the jaws look the same every 180 degrees."""
    return angle + period * round((near - angle) / period)


def jaw_yaw_from_joints(joints, flange_pose) -> float | None:
    """The jaws' travel direction's yaw in the base frame (degrees, defined mod 180), from the arm's FK, or None when
    the tool isn't pointing down (then a yaw says little)."""
    rotation = np.asarray(flange_pose(joints))[:3, :3]
    tool, jaw = rotation @ np.array(TOOL_AXIS_FLANGE), rotation @ np.array(JAW_AXIS_FLANGE)
    if tool[2] > -0.95:
        return None
    return math.degrees(math.atan2(jaw[1], jaw[0]))


def grasp_target(rollout: Rollout, jaw_yaw_at_r0: float, near_r: float) -> tuple[float, float, float]:
    """Where the fingertips go to grip (x, y in UF0 mm) and the R that turns the jaws to close across the part, plus the
    rollout's offset: dx along the jaws, dy across them, dyaw about z. A screw is gripped across its shank,
    GRASP_ALONG_MM from its head; a cube at its centre, with the jaws along its yaw (across two faces)."""
    px, py, yaw = rollout.part
    if rollout.kind == "cube":
        gx, gy, jaw_deg = px, py, yaw
    else:
        axis = math.radians(yaw)
        gx, gy, jaw_deg = px + GRASP_ALONG_MM * math.cos(axis), py + GRASP_ALONG_MM * math.sin(axis), yaw + 90.0
    jaw = math.radians(jaw_deg)
    jx, jy = math.cos(jaw), math.sin(jaw)
    x = gx + rollout.dx_mm * jx - rollout.dy_mm * jy  # dy along z cross the jaw direction
    y = gy + rollout.dx_mm * jy + rollout.dy_mm * jx
    r = nearest_equivalent(wrap180(jaw_deg + rollout.dyaw_deg - jaw_yaw_at_r0), near_r)
    return x, y, wrap180(r) if abs(r) > 360 else r


def segment(start, end, step_mm: float, gripper: float) -> list[list[float]]:
    """Rows from start to end (x, y, z, w, p, r), at most step_mm and TURN_STEP_DEG apart, excluding start."""
    a, b = np.asarray(start[:6], float), np.asarray(end[:6], float)
    turn = np.array([wrap180(b[i] - a[i]) for i in (3, 4, 5)])
    distance = float(np.linalg.norm(b[:3] - a[:3]))
    n = max(1, math.ceil(distance / step_mm), math.ceil(float(np.abs(turn).max()) / TURN_STEP_DEG))
    rows = []
    for k in range(1, n + 1):
        f = k / n
        position = a[:3] + f * (b[:3] - a[:3])
        angles = a[3:] + f * turn
        rows.append([*position.round(3).tolist(), *angles.round(3).tolist(), gripper])
    return rows


def hold(pose, gripper: float, n: int) -> list[list[float]]:
    return [[*list(pose[:6]), gripper] for _ in range(n)]


def check_rows(rows: list[list[float]]) -> list[str]:
    """Rows the cell would reject or the arm can't reach."""
    problems = []
    for i, row in enumerate(rows):
        for k, (lo, hi) in enumerate(TCP_BOX_MM):
            if not lo <= row[k] <= hi:
                problems.append(f"row {i}: {'xyz'[k]} {row[k]:.1f} outside [{lo:g}, {hi:g}] mm")
        if math.hypot(row[0], row[1]) > REACH_MM:
            problems.append(f"row {i}: {math.hypot(row[0], row[1]):.0f} mm from the base axis, past {REACH_MM:g}")
    return problems


def tip_z(height_above_surface_mm: float) -> float:
    """The TCP z (UF0) that puts our fingertips this high above the surface."""
    return SURFACE_Z_MM + height_above_surface_mm + TIP_BELOW_TCP_MM


def plan_pick_and_drop(rollout: Rollout, start, jaw_yaw_at_r0: float) -> list[list[float]]:
    """From above the part (start, already aimed): down, close, up, over the bin turned to the drop yaw, open, up."""
    x, y, r = grasp_target(rollout, jaw_yaw_at_r0, start[5])
    above = [x, y, tip_z(APPROACH_HEIGHT_MM), -180.0, 0.0, r]
    grip = [x, y, tip_z(rollout.tip_mm), -180.0, 0.0, r]
    lifted = [x, y, tip_z(CARRY_HEIGHT_MM), -180.0, 0.0, r]
    bx, by, bin_yaw = rollout.bin
    drop_r = nearest_equivalent(wrap180(bin_yaw + DROP_JAW_YAW_FROM_BIN_DEG - jaw_yaw_at_r0), r)
    over_bin = [bx, by, tip_z(CARRY_HEIGHT_MM), -180.0, 0.0, drop_r]
    drop = [bx, by, tip_z(BIN_HEIGHT_MM + DROP_ABOVE_BIN_MM), -180.0, 0.0, drop_r]
    rows = segment(start, above, FINE_STEP_MM, 0.0)
    rows += segment(above, grip, FINE_STEP_MM, 0.0)
    rows += hold(grip, 1.0, GRIP_DWELL_ROWS)
    rows += segment(grip, lifted, FINE_STEP_MM, 1.0)
    rows += segment(lifted, over_bin, TRAVEL_STEP_MM, 1.0)
    rows += segment(over_bin, drop, FINE_STEP_MM, 1.0)
    rows += hold(drop, 0.0, GRIP_DWELL_ROWS)
    rows += segment(drop, over_bin, TRAVEL_STEP_MM, 0.0)
    return rows


def _flange_pose():
    """The client package's FK (calibration/geometry.py), or None outside it."""
    try:
        from calibration.geometry import flange_pose
    except ImportError:
        return None
    return flange_pose


class Policy:
    CAMERAS = ["table", "side", "wrist"]  # all three are recorded either way; the policy itself doesn't look
    IMAGE_SIZE = (640, 360)
    IMAGE_FORMAT = "jpeg"  # nothing reads the images: keep them small
    ACTION = "tcp"
    PREFETCH = False
    DEPTH = []
    DT = DT_S

    def __init__(self, checkpoint: str | None = None):
        self.flange_pose = _flange_pose()
        if self.flange_pose is None:
            logger.warning("calibration.geometry not found: the jaws' direction can't be measured, using JAW_YAW_AT_R0_DEG")
        self.reset()

    def reset(self) -> None:
        """Called at the start of every rollout."""
        self.phase = "approach"
        self.queue: list[list[float]] = []
        self.last: list[float] | None = None
        self.jaw_yaw_at_r0 = JAW_YAW_AT_R0_DEG
        self.measured = False
        self.rollout: Rollout | None = None
        self.record: dict = {}

    def act(self, obs: dict):
        if self.rollout is None:
            self.rollout = parse_instruction((obs.get("trial") or {}).get("instruction"))
            if self.rollout.trial is None:
                logger.warning("no [c2f ...] tag in the instruction: default screw and bin poses, no offset")
            self.record = {"t": time.time(), "trial_id": (obs.get("trial") or {}).get("trial_id"), "rollout": self.rollout.__dict__}
        self._measure(obs)
        while not self.queue:  # a refused plan leaves it empty and moves on to "done", which always fills it
            self._next_phase(obs)
        chunk, self.queue = self.queue[:MAX_CHUNK], self.queue[MAX_CHUNK:]
        self.last = chunk[-1]
        return chunk

    def _measure(self, obs: dict) -> None:
        """Update the jaws' yaw at R = 0 from this observation, when the tool points down and the TCP pose is known."""
        tcp = obs.get("tcp_pose")
        if self.flange_pose is None or tcp is None or obs.get("joints") is None:
            return
        jaw = jaw_yaw_from_joints(obs["joints"][:6], self.flange_pose)
        if jaw is None:
            return
        at_r0 = wrap180(jaw - float(tcp[5]))
        jump = nearest_equivalent(at_r0 - self.jaw_yaw_at_r0, 0.0)
        if self.measured and abs(jump) > MAX_JAW_JUMP_DEG:
            logger.error("jaws measured %.1f deg from the last measurement (joints and tcp_pose disagree?): keeping it", jump)
            return
        if not self.measured or abs(jump) > 0.5:
            logger.info("jaws measured: yaw %.1f deg at R %.1f, so %.1f deg at R = 0", jaw, tcp[5], at_r0)
            self.record.setdefault("jaw_measurements", []).append({"jaw_yaw_deg": jaw, "r_deg": float(tcp[5]), "at_r0_deg": at_r0})
        self.jaw_yaw_at_r0, self.measured = at_r0, True

    def _current(self, obs: dict) -> list[float] | None:
        tcp = obs.get("tcp_pose")
        return list(tcp[:6]) if tcp is not None else (self.last[:6] if self.last else None)

    def _next_phase(self, obs: dict) -> None:
        rollout, current = self.rollout, self._current(obs)
        if self.phase == "approach":
            near = current[5] if current else 0.0
            x, y, r = grasp_target(rollout, self.jaw_yaw_at_r0, near)
            above = [x, y, tip_z(APPROACH_HEIGHT_MM), -180.0, 0.0, r]
            rows = segment(current, above, TRAVEL_STEP_MM, 0.0) if current else [[*above, 0.0]]
            self._set(rows, "aim")
        elif self.phase == "aim":
            # Above the part: aim again with the jaws as measured here, then the rest of the rollout.
            x, y, r = grasp_target(rollout, self.jaw_yaw_at_r0, current[5])
            start = current
            if abs(wrap180(r - current[5])) > REAIM_TOLERANCE_DEG:
                logger.info("re-aiming the jaws by %.1f deg before descending", wrap180(r - current[5]))
            self.record |= {"jaw_yaw_at_r0_deg": self.jaw_yaw_at_r0, "jaws_measured": self.measured, "grasp_xy_r": [x, y, r]}
            self._set(plan_pick_and_drop(rollout, start, self.jaw_yaw_at_r0), "done")
            self._log()
        else:  # done: hold still where we last sent the arm, jaws open
            pose = self.last[:6] if self.last else current
            if pose is None:
                raise RuntimeError("nothing to hold: no TCP pose was observed or commanded yet")
            self.queue = [[*pose, 0.0]]

    def _set(self, rows: list[list[float]], next_phase: str) -> None:
        if problems := check_rows(rows):
            logger.error("plan refused, holding still: %s", "; ".join(problems[:5]))
            self.phase, self.queue = "done", []
            return
        self.phase, self.queue = next_phase, rows

    def _log(self) -> None:
        try:
            with LOG_FILE.open("a") as f:
                f.write(json.dumps(self.record) + "\n")
        except OSError as e:
            logger.warning("couldn't write %s: %s", LOG_FILE, e)
