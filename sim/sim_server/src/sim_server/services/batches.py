"""A batch in the twin's units, the grasp each design commands, and how a batch is split across environments. Isaac-free.

Requests arrive in millimetres, grams and degrees (routers/evaluations.py validates their shape); the twin works in metres,
kilograms and degrees. Everything is converted here, once, so the Isaac side never sees millimetres.
"""

from collections.abc import Sequence

from sim_server.models.finger import FingerDesign, Piece, Point
from sim_server.models.grasp import GraspSettings
from sim_server.models.gripper import GripperGeometry
from sim_server.models.offset import Offset
from sim_server.models.part import Part

M_PER_MM = 1e-3
KG_PER_G = 1e-3
# scene_config.CUBE_JAW_HALF_TARGET closes each jaw 0.3 mm past first contact at the hooked tip ("per-jaw seating travel").
STOCK_SEATING = 0.0003
MIN_PIECE_VOLUME_MM3 = 1e-3  # below this a piece is flat or degenerate and PhysX can't cook a convex hull from it


def part_from_mm(
    shape: str,
    *,
    mass_g: float,
    diameter_mm: float | None = None,
    length_mm: float | None = None,
    upright: bool = True,
    box_mm: Sequence[float] | None = None,
) -> Part:
    """Fields that don't apply to the shape are ignored (the app sends all of them)."""
    if mass_g <= 0:
        raise ValueError("mass_g must be positive")
    if shape == "cylinder":
        if not diameter_mm or not length_mm or diameter_mm <= 0 or length_mm <= 0:
            raise ValueError("a cylinder needs positive diameter_mm and length_mm")
        d, length = diameter_mm * M_PER_MM, length_mm * M_PER_MM
        size, axis = ((d, d, length), "z") if upright else ((d, length, d), "y")
        return Part(shape="cylinder", size=size, mass=mass_g * KG_PER_G, cylinder_axis=axis)
    if shape == "box":
        if box_mm is None or len(box_mm) != 3 or min(box_mm) <= 0:
            raise ValueError("a box needs box_mm = [along the closing direction, across it, height], all positive")
        return Part(shape="box", size=tuple(v * M_PER_MM for v in box_mm), mass=mass_g * KG_PER_G)
    raise ValueError(f"unknown part shape {shape!r}; use 'cylinder' or 'box'")


def piece_volume(points: Sequence[Point], triangles: Sequence[tuple[int, int, int]]) -> float:
    """Signed volume of a closed triangle mesh (positive when the faces point outward)."""
    total = 0.0
    for i, j, k in triangles:
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = points[i], points[j], points[k]
        total += ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)
    return total / 6


def design_from_mm(
    design_id: str,
    *,
    pieces_mm: Sequence[tuple[Sequence[Sequence[float]], Sequence[Sequence[int]]]] | None = None,
    friction: Sequence[float] | None = None,
    tip_height_mm: float | None = None,
    jaw_close_mm: float | None = None,
) -> FingerDesign:
    """pieces_mm: [(points, triangles), ...] in G millimetres. No pieces means stock fingers."""
    tip = None if tip_height_mm is None else tip_height_mm * M_PER_MM
    jaw = None if jaw_close_mm is None else jaw_close_mm * M_PER_MM
    if pieces_mm is None:
        if friction is not None:
            raise ValueError(f"design {design_id!r}: stock fingers keep the twin's own materials; drop 'friction' or send 'pieces'")
        return FingerDesign(id=design_id, tip_height=tip, jaw_close=jaw)
    if not pieces_mm:
        raise ValueError(f"design {design_id!r}: 'pieces' is empty; omit it for stock fingers")
    if friction is None or tip_height_mm is None or jaw_close_mm is None:
        raise ValueError(f"design {design_id!r}: custom fingers need 'friction', 'tip_height_mm' and 'jaw_close_mm'")
    pieces = []
    for n, (points, triangles) in enumerate(pieces_mm):
        tris = tuple((int(a), int(b), int(c)) for a, b, c in triangles)
        if any(not 0 <= i < len(points) for t in tris for i in t):
            raise ValueError(f"design {design_id!r}, piece {n}: a triangle indexes a point that doesn't exist")
        if abs(piece_volume(points, tris)) < MIN_PIECE_VOLUME_MM3:
            raise ValueError(f"design {design_id!r}, piece {n}: zero volume (flat, degenerate, or triangles don't close the hull)")
        pieces.append(Piece(points=tuple((x * M_PER_MM, y * M_PER_MM, z * M_PER_MM) for x, y, z in points), triangles=tris))
    return FingerDesign(
        id=design_id, pieces=tuple(pieces), friction=(float(friction[0]), float(friction[1])), tip_height=tip, jaw_close=jaw
    )


def offset_from_mm(dx_mm: float, dy_mm: float, yaw_deg: float) -> Offset:
    return Offset(dx=dx_mm * M_PER_MM, dy=dy_mm * M_PER_MM, yaw_deg=float(yaw_deg))


def grasp_settings(design: FingerDesign, part: Part, geo: GripperGeometry) -> GraspSettings:
    """Custom fingers use the design's own values. Stock fingers follow the twin's cube rule (CUBE_TIP_CLEARANCE,
    CUBE_JAW_HALF_TARGET) with the cube edge replaced by the part's width along the closing direction: tips 2.5 mm above
    the surface, each jaw closed to 0.3 mm past where its hook tip meets the part, within the stroke."""
    if not design.is_stock:
        return GraspSettings(tip_height=design.tip_height, jaw_close=design.jaw_close)
    seated = part.width / 2 - geo.finger_inner_tip - STOCK_SEATING
    jaw = min(geo.jaw_open, max(geo.jaw_closed, seated))
    return GraspSettings(
        tip_height=geo.tip_clearance if design.tip_height is None else design.tip_height,
        jaw_close=jaw if design.jaw_close is None else design.jaw_close,
    )


def stock_fits(part: Part, geo: GripperGeometry) -> bool:
    """Whether the part's nominal width fits between the open stock hook tips at all. If not, every grasp fails and
    isn't simulated (the fingertips would land on top of the part)."""
    return part.width < geo.open_tip_gap


def design_warnings(design: FingerDesign, settings: GraspSettings) -> list[str]:
    """Problems a custom design will likely run into, for the log. They don't stop the grasp."""
    if design.is_stock:
        return []
    points = [p for piece in design.pieces for p in piece.points]
    warnings = []
    lowest = min(z for _, _, z in points)
    if lowest < -settings.tip_height:
        warnings.append(
            f"pieces reach {-lowest * 1000:.2f} mm below the fingertip plane but the tips stop "
            f"{settings.tip_height * 1000:.2f} mm above the surface, so the fingers hit the work surface"
        )
    inner = min(x for x, _, _ in points)
    if inner < 0 and settings.jaw_close < -inner:
        warnings.append(
            f"the two fingers meet at a jaw opening of {-inner * 1000:.2f} mm, before reaching jaw_close "
            f"{settings.jaw_close * 1000:.2f} mm, so they squeeze each other rather than only the part"
        )
    return warnings


def chunk_grasps(pairs: Sequence[tuple[int, int]], n_envs: int) -> list[list[tuple[int, int]]]:
    """Splits (design, offset) pairs into chunks of at most n_envs, one pair per environment. Pairs come design-major,
    so each design's copies are contiguous within a chunk and share its fingers and joint trajectory."""
    if n_envs < 1:
        raise ValueError("n_envs must be at least 1")
    return [list(pairs[i : i + n_envs]) for i in range(0, len(pairs), n_envs)]
