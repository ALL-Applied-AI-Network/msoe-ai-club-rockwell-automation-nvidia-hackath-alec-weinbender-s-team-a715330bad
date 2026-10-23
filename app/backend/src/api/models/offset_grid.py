"""The camera errors every design is tested at, and how its results there become an expected success rate.

Every design is tested at the same fixed grid of offsets instead of random draws. A simulated grasp at a given offset comes
out (nearly) the same every time, so the only noise in a sampled success rate is which offsets were drawn; the grid removes
it. One set of results can also be scored at any error model by re-weighting, without simulating again: another sigma, a
bias, a range of sigmas, another task (success per point comes from api/models/task.py: Task.success).

Offsets are in the gripper's frame at the grasp: dx along the jaws' closing direction, dy across it, yaw about the approach
axis. The error model (api/models/error_model.py) draws dx and dy as independent normals with sigma_mm around the bias (so
without one the radial error is Rayleigh) and yaw as a normal with sigma_deg.

Each point stands for the cell around it: the centre for the disc inside half the first ring, each ring point for the
annular sector running halfway to the neighbouring rings and over its 1/n_directions of the turn, each yaw for the
interval halfway to its neighbours. A point's weight is its cell's probability. Error beyond the outermost cell isn't
tested and gets no weight, so it counts as a failure and the weights sum to slightly under 1.
"""

import math
from functools import lru_cache
from itertools import pairwise

import numpy as np
from pydantic import BaseModel, model_validator

from api.models.error_model import CURVE_SIGMAS_MM, ErrorModel
from api.models.part import Part

YAW_SPREAD = 1.5  # the yaw layers sit at 0 and this many sigma_deg either side
_GL_NODES, _GL_WEIGHTS = np.polynomial.legendre.leggauss(6)
_STEP_SIGMAS = 1.0  # quadrature sub-intervals are at most this many sigmas long (or of arc, at a cell's outer edge)
_CUTOFF_SIGMAS = 9.0  # cells further than this from the bias hold under 1e-17 of the mass and are skipped


class GridPoint(BaseModel):
    dx: float
    dy: float
    yaw_deg: float
    weight: float  # the probability of its cell under the error model


class GridCircle(BaseModel):
    label: str  # "1σ" or "2σ"
    sigma_mm: float  # the sigma it's drawn for (a range's largest)
    centre_mm: tuple[float, float]  # the bias
    radius_mm: float


class GridPreview(BaseModel):
    """What step 7 draws for an error model: the grid, its weights, the error's 1σ and 2σ circles, and warnings."""

    points: list[GridPoint]  # every offset with its weight, aligned with OffsetGrid.points()
    circles: list[GridCircle]
    outer_ring_mm: float  # the outermost tested ring
    covered_to_mm: float  # where its cells end: error beyond counts as a miss
    yaws_deg: list[float]  # the yaw layers ([0] when yaw isn't tested)
    n_offsets: int
    coverage: float  # the sum of the weights: the chance the error lands on the grid at all
    warnings: list[str]


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
    def for_part(cls, part: Part, error: ErrorModel) -> "OffsetGrid":
        """The search grid for a part: yaw is tested (at 0 and YAW_SPREAD sigma either side) unless the part is round from
        above (an upright cylinder) or the error model has no yaw. Boxes, lying cylinders and meshes get three layers."""
        return cls.for_parts([part], error)

    @classmethod
    def for_parts(cls, parts: list[Part], error: ErrorModel) -> "OffsetGrid":
        """One search grid for the same part in several resting poses (a job's): yaw is tested unless every pose is round
        from above, so all poses' results line up point for point."""
        if all(part.round_from_above for part in parts) or error.sigma_deg <= 0:
            return cls()
        spread = YAW_SPREAD * error.sigma_deg
        return cls(yaws_deg=[-spread, 0.0, spread])

    def refined(self) -> "OffsetGrid":
        """A denser grid for re-validating finalists: a ring inside the first and halfway between each pair, and twice the
        directions. It contains every point of this grid."""
        radii = sorted({self.radii_mm[0] / 2, *self.radii_mm, *((a + b) / 2 for a, b in pairwise(self.radii_mm))})
        return OffsetGrid(radii_mm=radii, n_directions=2 * self.n_directions, yaws_deg=self.yaws_deg)

    @property
    def per_yaw(self) -> int:
        return 1 + len(self.radii_mm) * self.n_directions

    @property
    def size(self) -> int:
        return len(self.yaws_deg) * self.per_yaw

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

    def weights(self, error: ErrorModel) -> list[float]:
        """Each point's probability under the error model, aligned with points(). Without a bias these are the exact
        Rayleigh masses of the rings, shared equally between directions; with one, each cell's mass under N(bias, sigma^2 I)
        by Gauss-Legendre quadrature over its annular sector. Designing for a range averages the weights over its sigmas.
        Yaw weights are normal masses either way. Cached: rescoring calls this once per design."""
        bx, by = error.bias_xy
        return list(
            _weights(tuple(self.radii_mm), self.n_directions, tuple(self.yaws_deg), tuple(error.sigmas_mm), error.sigma_deg, bx, by)
        )

    def expected_success(self, success: list[bool], error: ErrorModel) -> float:
        """The probability that a grasp succeeds under the error model, from one result per point (held, or the task's
        success: Task.success)."""
        self._check_results(success)
        return sum(w for w, ok in zip(self.weights(error), success, strict=True) if ok)

    def capture_radius(self, success: list[bool]) -> float | None:
        """The largest radius out to which every grasp succeeded, at every yaw: "holds all grasps within X mm". 0 if only
        the centre did, None if even the centre failed."""
        self._check_results(success)
        n_yaws, n = len(self.yaws_deg), self.n_directions
        ok = [all(success[y * self.per_yaw + i] for y in range(n_yaws)) for i in range(self.per_yaw)]
        if not ok[0]:
            return None
        radius = 0.0
        for k, r in enumerate(self.radii_mm):
            if not all(ok[1 + k * n : 1 + (k + 1) * n]):
                break
            radius = r
        return radius

    def curve(self, success: list[bool], error: ErrorModel) -> dict[str, float]:
        """Expected success against position error: at each of CURVE_SIGMAS_MM, with this model's bias and yaw. Keyed by
        the sigma as text ("0.5", "1", ...), so it survives JSON."""
        return {f"{sigma:g}": self.expected_success(success, error.at_sigma(sigma)) for sigma in CURVE_SIGMAS_MM}

    def warnings(self, error: ErrorModel) -> list[str]:
        """What the user should know about this grid under this error model: errors it barely covers."""
        sigma, outer = max(error.sigmas_mm), self.radii_mm[-1]
        reach = error.bias_mm + 2 * sigma
        if reach > outer:
            return [f"bias + 2σ ({reach:.1f} mm) reaches past the {outer:g} mm outer ring: errors beyond the grid count as misses"]
        return []

    def preview(self, error: ErrorModel) -> GridPreview:
        """The grid under an error model, for step 7's picture."""
        weights = self.weights(error)
        sigma, centre = max(error.sigmas_mm), tuple(round(v, 9) for v in error.bias_xy)
        return GridPreview(
            points=[GridPoint(**point, weight=w) for point, w in zip(self.points(), weights, strict=True)],
            circles=[GridCircle(label=f"{k}σ", sigma_mm=sigma, centre_mm=centre, radius_mm=k * sigma) for k in (1, 2)],
            outer_ring_mm=self.radii_mm[-1],
            covered_to_mm=_cells([0.0, *self.radii_mm])[-1][1],
            yaws_deg=self.yaws_deg,
            n_offsets=len(weights),
            coverage=sum(weights),
            warnings=self.warnings(error),
        )

    def _check_results(self, results: list[bool]) -> None:
        if len(results) != self.size:
            raise ValueError(f"expected {self.size} results (one per grid point), got {len(results)}")


@lru_cache(maxsize=256)
def _weights(
    radii: tuple[float, ...], n: int, yaws: tuple[float, ...], sigmas: tuple[float, ...], sigma_deg: float, bx: float, by: float
) -> tuple[float, ...]:
    cells = _cells([0.0, *radii])
    position = np.mean([_position_weights(cells, n, sigma, bx, by) for sigma in sigmas], axis=0)
    yaw = [1.0] if len(yaws) == 1 else [_normal_mass(lo, hi, sigma_deg) for lo, hi in _cells(list(yaws))]
    return tuple(float(y * w) for y in yaw for w in position)


def _position_weights(cells: list[tuple[float, float]], n: int, sigma: float, bx: float, by: float) -> np.ndarray:
    """One yaw layer's weights: the centre's disc, then each ring's n sectors. cells[0] is the centre's radial interval
    (its low end, below 0, is clamped), cells[1:] the rings'."""
    if bx == 0 and by == 0:
        radial = [_rayleigh_mass(max(lo, 0.0), hi, sigma) for lo, hi in cells]
        return np.array([radial[0], *(mass / n for mass in radial[1:] for _ in range(n))])
    if sigma <= 0:
        return _point_mass(cells, n, bx, by)
    disc = _sector_masses(0.0, cells[0][1], 1, sigma, bx, by)
    return np.concatenate([disc, *(_sector_masses(lo, hi, n, sigma, bx, by) for lo, hi in cells[1:])])


def _sector_masses(lo: float, hi: float, n: int, sigma: float, bx: float, by: float) -> np.ndarray:
    """The mass of N((bx, by), sigma^2 I) in each of the n sectors of the annulus lo <= r < hi, sector j centred on the
    direction 2 pi j / n: composite Gauss-Legendre in r and theta, with sub-intervals no longer than _STEP_SIGMAS sigmas."""
    b = math.hypot(bx, by)
    if max(lo - b, b - hi, 0.0) > _CUTOFF_SIGMAS * sigma:
        return np.zeros(n)
    sector = 2 * math.pi / n
    r, wr = _nodes(lo, hi, _STEP_SIGMAS * sigma)
    t, wt = _nodes(-sector / 2, sector / 2, _STEP_SIGMAS * sigma / hi)
    theta = t[None, :] + sector * np.arange(n)[:, None]  # (n, nodes)
    x = r[:, None, None] * np.cos(theta)[None] - bx
    y = r[:, None, None] * np.sin(theta)[None] - by
    density = np.exp(-(x * x + y * y) / (2 * sigma * sigma)) * r[:, None, None] / (2 * math.pi * sigma * sigma)
    return np.einsum("i,ijk,k->j", wr, density, wt)


def _nodes(a: float, b: float, step: float) -> tuple[np.ndarray, np.ndarray]:
    """Composite Gauss-Legendre nodes and weights over [a, b], in sub-intervals no longer than step."""
    m = max(1, math.ceil((b - a) / step))
    edges = np.linspace(a, b, m + 1)
    half, mid = (edges[1:] - edges[:-1]) / 2, (edges[1:] + edges[:-1]) / 2
    return (mid[:, None] + half[:, None] * _GL_NODES).ravel(), (half[:, None] * _GL_WEIGHTS).ravel()


def _point_mass(cells: list[tuple[float, float]], n: int, bx: float, by: float) -> np.ndarray:
    """No spread, only a bias: all the weight on the cell holding the bias (none if it's off the grid)."""
    out = np.zeros(1 + (len(cells) - 1) * n)
    r = math.hypot(bx, by)
    if r < cells[0][1]:
        out[0] = 1.0
        return out
    for k, (lo, hi) in enumerate(cells[1:]):
        if lo <= r < hi:
            out[1 + k * n + round(math.atan2(by, bx) / (2 * math.pi / n)) % n] = 1.0
    return out


def _increasing(values: list[float]) -> bool:
    return all(b > a for a, b in pairwise(values))


def _cells(values: list[float]) -> list[tuple[float, float]]:
    """The interval each value stands for: halfway to its neighbours, and as far again past either end."""
    mids = [(a + b) / 2 for a, b in pairwise(values)]
    first, last = values[0] - (mids[0] - values[0]), values[-1] + (values[-1] - mids[-1])
    return list(pairwise([first, *mids, last]))


def _rayleigh_mass(lo: float, hi: float, sigma: float) -> float:
    """P(lo <= radius < hi) when dx and dy are independent zero-mean normals with this sigma."""
    if sigma <= 0:
        return 1.0 if lo <= 0 < hi else 0.0
    return math.exp(-(lo**2) / (2 * sigma**2)) - math.exp(-(hi**2) / (2 * sigma**2))


def _normal_mass(lo: float, hi: float, sigma: float) -> float:
    """P(lo <= x < hi) for a zero-mean normal with this sigma."""
    if sigma <= 0:
        return 1.0 if lo <= 0 < hi else 0.0
    return 0.5 * (math.erf(hi / (sigma * math.sqrt(2))) - math.erf(lo / (sigma * math.sqrt(2))))
