"""The robot's grasp motion, planned once per design at the nominal part pose with the twin's own IK. Isaac-free (numpy).

It follows sort_scene.py: the same home pose (fingertips at (0.30, 0, 0.24), pointing down), the same segments and
durations, the same easing and wrist turn, 30 control frames per second with two 1/60 s physics steps each, and the same
IK acceptance test (converged, within 1 mm, jaws aligned). Of the twin's pick it uses approach, descend, close, dwell and
lift; the held check (the part's centre rose more than 25 mm) is taken at the end of the lift, as the twin does.

sort_scene.py can't be imported here (it pulls in OpenCV through cube_pose), so its ease(), turn() and segment table are
restated below; tests/robot/test_motion.py checks them against the twin's own segments().

The plan depends only on the design's tip height and jaw target, never on the part's true pose, so every copy of a
design in the vectorised path shares one joint trajectory.
"""

from dataclasses import dataclass

import numpy as np

from sim_server.models.grasp import GraspPlanError
from sim_server.models.gripper import GripperGeometry
from sim_server.robot.poses import NOMINAL_SITE_XY, NOMINAL_SPREAD_XY

FPS = 30  # sort_scene.py: "Use 30 fps: two 1/60 s physics steps per video frame"
PHYSICS_DT = 1 / 60
PHYSICS_STEPS_PER_FRAME = 2
HOME_TIP = (0.30, 0.0, 0.24)  # sort_scene.py: home = np.array([0.30, 0.0, 0.24])
DOWN = (0.0, 0.0, -1.0)
LIFT_HEIGHT = 0.13  # sort_scene.segments(): up = p + [0, 0, 0.13]
HELD_RISE = 0.025  # sort_scene.py: an object counts as lifted when its centre rose more than 0.025 m
# sort_scene.segments(), first five entries: (name, seconds). Jaws stay open until "close", then hold the target.
SEGMENT_SECONDS = (("approach", 1.2), ("descend", 0.8), ("close", 0.6), ("dwell", 0.5), ("lift", 0.8))


def ease(t: float) -> float:
    return t * t * (3 - 2 * t)


def turn(a, b, t: float) -> np.ndarray:
    """Rotate horizontal direction a toward b by fraction t (sort_scene.turn)."""
    a, b = np.array(a, float), np.array(b, float)
    angle = np.arctan2(a[0] * b[1] - a[1] * b[0], np.dot(a[:2], b[:2])) * t
    c, s = np.cos(angle), np.sin(angle)
    return np.array([a[0] * c - a[1] * s, a[0] * s + a[1] * c, 0.0])


@dataclass(frozen=True)
class GraspPlan:
    """A runtime holder for numpy trajectories, not a domain model."""

    arm: np.ndarray  # (frames, 6): J1..J6 position targets, radians
    jaw: np.ndarray  # (frames,): per-jaw opening, metres; cell.jaw_targets() turns it into the prismatic joint targets
    segment_end: dict[str, int]  # number of frames done when each segment ends

    @property
    def frames(self) -> int:
        return len(self.jaw)


class GraspPlanner:
    """Solves the home pose once and caches one plan per (tip height, jaw target). Needs twin.use_twin() first."""

    def __init__(self, geo: GripperGeometry, site_xy=NOMINAL_SITE_XY, nominal_spread_xy=NOMINAL_SPREAD_XY):
        import fk
        import ik
        import scene_config as C

        self._fk, self._ik, self._geo = fk, ik, geo
        ik.set_tool_axis(C.TOOL_AXIS)  # module globals in the twin's ik.py; sort_scene.py sets the same values
        ik.set_spread_axis(C.FINGER_SPREAD_AXIS)
        self._spread_axis = np.array(C.FINGER_SPREAD_AXIS, float)
        self._tool = tuple(np.array(C.TOOL_AXIS, float) * geo.tip_offset)
        self._limits = np.deg2rad([C.JOINT_LIMITS_DEG[f"J{i}"] for i in range(1, 7)])
        self.site_xy = tuple(site_xy)
        q0 = np.deg2rad([C.HOME_POSE_DEG[f"J{i}"] for i in range(1, 7)])
        q, ok = ik.solve(q0, np.array(HOME_TIP), DOWN, self._limits, tool_offset=self._tool)
        if not ok:
            raise GraspPlanError("Home IK failed")
        self.q_home = q
        # Like sort_scene.py, take whichever of the two equivalent jaw directions the wrist is already closest to.
        r, _ = fk.fk(q)
        spread = np.array([*nominal_spread_xy, 0.0], float)
        spread /= np.linalg.norm(spread)
        self.spread = -spread if np.dot(r @ self._spread_axis, spread) < 0 else spread  # world direction toward JawL
        self._plans: dict[tuple[float, float], GraspPlan] = {}

    @property
    def spread_xy(self) -> tuple[float, float]:
        return float(self.spread[0]), float(self.spread[1])

    def plan(self, tip_height: float, jaw_close: float) -> GraspPlan:
        key = (round(tip_height, 7), round(jaw_close, 7))  # 0.1 um: closer than that is the same plan
        if key not in self._plans:
            self._plans[key] = self._solve(tip_height, jaw_close)
        return self._plans[key]

    def _solve(self, tip_height: float, jaw_close: float) -> GraspPlan:
        fk, ik, geo = self._fk, self._ik, self._geo
        pick = np.array([*self.site_xy, geo.surface_dz + tip_height])
        up = pick + [0.0, 0.0, LIFT_HEIGHT]
        opened = geo.jaw_open
        segments = [  # (name, from, to, jaw from, jaw to), as in sort_scene.segments()
            ("approach", np.array(HOME_TIP), up, opened, opened),
            ("descend", up, pick, opened, opened),
            ("close", pick, pick, opened, jaw_close),
            ("dwell", pick, pick, jaw_close, jaw_close),
            ("lift", pick, up, jaw_close, jaw_close),
        ]
        q = self.q_home.copy()
        arm, jaw, segment_end = [], [], {}
        for (name, p0, p1, j0, j1), (_, seconds) in zip(segments, SEGMENT_SECONDS, strict=True):
            spread_start = None
            if name == "approach":  # turn the wrist from wherever home left it, as sort_scene.py does
                r, _ = fk.fk(q)
                s = r @ self._spread_axis
                s[2] = 0
                spread_start = s / np.linalg.norm(s)
            n = round(seconds * FPS)
            for i in range(n):
                t = ease((i + 1) / n)
                target = p0 + (p1 - p0) * t
                direction = turn(spread_start, self.spread, t) if spread_start is not None else self.spread
                q, ok = ik.solve(q, target, DOWN, self._limits, tool_offset=self._tool, spread_dir=direction)
                if not ok:
                    q, ok = ik.solve(q, target, DOWN, self._limits, tool_offset=self._tool, spread_dir=direction, iters=500, damping=0.02)
                r, actual = fk.tool_pose(q, self._tool)
                aligned = abs(np.dot(r @ self._spread_axis, direction)) > 0.999
                if not ok or np.linalg.norm(actual - target) > 0.001 or not aligned:
                    raise GraspPlanError(
                        f"IK failed during {name}, frame {i}, tip height {tip_height * 1000:.2f} mm; refusing an off-target grasp"
                    )
                arm.append(q.copy())
                jaw.append(j0 + (j1 - j0) * t)
            segment_end[name] = len(jaw)
        return GraspPlan(np.array(arm), np.array(jaw), segment_end)
