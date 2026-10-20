"""The camera errors every design is tested at, and how its results there become an expected success rate.

Every design is tested at the same fixed grid of offsets instead of random draws. A simulated grasp at a given offset comes
out (nearly) the same every time, so the only noise in a sampled success rate is which offsets were drawn; the grid removes
it. One set of results can also be scored at any error level by re-weighting, without simulating again.

Offsets are in the gripper's frame at the grasp: dx along the jaws' closing direction, dy across it, yaw about the approach
axis. The error model draws dx and dy as independent normals with sigma_mm (so the radial error is Rayleigh) and yaw as a
normal with sigma_deg.
"""

import math
from itertools import pairwise

from pydantic import BaseModel, model_validator

from api.models.part import Part


class OffsetGrid(BaseModel):
    """Rings of offsets around the nominal grasp, evenly spaced around each ring, repeated at each yaw. A single yaw (the
    default) means yaw isn't tested, which suits parts that look the same at any yaw, like an upright cylinder."""

    radii_mm: list[float] = [1, 2, 3, 4, 5, 6, 7, 8, 10, 12]
    n_directions: int = 8
    yaws_deg: list[float] = [0]

    @model_validator(mode="after")
    def _check(self) -> "OffsetGrid":
        if not self.radii_mm or self.radii_mm[0] <= 0 or not _increasing(self.radii_mm):
            raise ValueError("radii_mm must be positive and strictly increasing")
        if self.n_directions < 1:
            raise ValueError("n_directions must be at least 1")
        if not self.yaws_deg or not _increasing(self.yaws_deg):
            raise ValueError("yaws_deg must be non-empty and strictly increasing")
        return self

    @classmethod
    def for_part(cls, part: Part, sigma_deg: float) -> "OffsetGrid":
        """The search grid for a part: yaw is tested (at 0 and 1.5 sigma either side) only if the part isn't round from above."""
        if part.round_from_above or sigma_deg <= 0:
            return cls()
        return cls(yaws_deg=[-1.5 * sigma_deg, 0.0, 1.5 * sigma_deg])

    def refined(self) -> "OffsetGrid":
        """A denser grid for re-validating finalists: a ring inside the first and halfway between each pair, and twice the
        directions. It contains every point of this grid."""
        radii = sorted({self.radii_mm[0] / 2, *self.radii_mm, *((a + b) / 2 for a, b in pairwise(self.radii_mm))})
        return OffsetGrid(radii_mm=radii, n_directions=2 * self.n_directions, yaws_deg=self.yaws_deg)

    @property
    def per_yaw(self) -> int:
        return 1 + len(self.radii_mm) * self.n_directions

    def points(self) -> list[dict]:
        """Every offset, in the sim's {dx, dy, yaw_deg} form: for each yaw, the centre, then each ring going round."""
        ring = [
            (math.cos(2 * math.pi * j / self.n_directions), math.sin(2 * math.pi * j / self.n_directions)) for j in range(self.n_directions)
        ]
        return [
            {"dx": round(r * c, 9), "dy": round(r * s, 9), "yaw_deg": yaw}
            for yaw in self.yaws_deg
            for r, c, s in [(0.0, 1.0, 0.0), *((r, c, s) for r in self.radii_mm for c, s in ring)]
        ]

    def weights(self, sigma_mm: float, sigma_deg: float) -> list[float]:
        """Each point's probability under the error model, aligned with points(). A point stands for the cell around it:
        rings split halfway between radii and share their probability equally between directions. Error beyond the
        outermost cell isn't tested and gets no weight, so it counts as a failure and the weights sum to slightly under 1."""
        radial = [_rayleigh_mass(max(lo, 0.0), hi, sigma_mm) for lo, hi in _cells([0.0, *self.radii_mm])]
        yaw = [1.0] if len(self.yaws_deg) == 1 else [_normal_mass(lo, hi, sigma_deg) for lo, hi in _cells(self.yaws_deg)]
        one_yaw = [radial[0], *(mass / self.n_directions for mass in radial[1:] for _ in range(self.n_directions))]
        return [y * w for y in yaw for w in one_yaw]

    def expected_success(self, held: list[bool], sigma_mm: float, sigma_deg: float) -> float:
        """The probability that a grasp holds under the error model, from one result per point."""
        self._check_results(held)
        return sum(w for w, ok in zip(self.weights(sigma_mm, sigma_deg), held, strict=True) if ok)

    def capture_radius(self, held: list[bool]) -> float | None:
        """The largest radius out to which every grasp held, at every yaw: "holds all grasps within X mm". 0 if only the
        centre held, None if even the centre failed."""
        self._check_results(held)
        n_yaws, n = len(self.yaws_deg), self.n_directions
        ok = [all(held[y * self.per_yaw + i] for y in range(n_yaws)) for i in range(self.per_yaw)]
        if not ok[0]:
            return None
        radius = 0.0
        for k, r in enumerate(self.radii_mm):
            if not all(ok[1 + k * n : 1 + (k + 1) * n]):
                break
            radius = r
        return radius

    def _check_results(self, held: list[bool]) -> None:
        if len(held) != len(self.yaws_deg) * self.per_yaw:
            raise ValueError(f"expected {len(self.yaws_deg) * self.per_yaw} results (one per grid point), got {len(held)}")


def _increasing(values: list[float]) -> bool:
    return all(b > a for a, b in pairwise(values))


def _cells(values: list[float]) -> list[tuple[float, float]]:
    """The interval each value stands for: halfway to its neighbours, and as far again past either end."""
    mids = [(a + b) / 2 for a, b in pairwise(values)]
    first, last = values[0] - (mids[0] - values[0]), values[-1] + (values[-1] - mids[-1])
    return list(pairwise([first, *mids, last]))


def _rayleigh_mass(lo: float, hi: float, sigma: float) -> float:
    """P(lo <= radius < hi) when dx and dy are independent normals with this sigma."""
    if sigma <= 0:
        return 1.0 if lo <= 0 < hi else 0.0
    return math.exp(-(lo**2) / (2 * sigma**2)) - math.exp(-(hi**2) / (2 * sigma**2))


def _normal_mass(lo: float, hi: float, sigma: float) -> float:
    """P(lo <= x < hi) for a zero-mean normal with this sigma."""
    if sigma <= 0:
        return 1.0 if lo <= 0 < hi else 0.0
    return 0.5 * (math.erf(hi / (sigma * math.sqrt(2))) - math.erf(lo / (sigma * math.sqrt(2))))
