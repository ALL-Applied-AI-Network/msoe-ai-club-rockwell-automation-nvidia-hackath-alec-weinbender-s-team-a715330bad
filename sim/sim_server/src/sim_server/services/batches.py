"""A batch in the twin's units, the grasp each design commands, and how a batch is split across environments. Isaac-free.

Requests arrive in millimetres, grams and degrees (routers/evaluations.py validates their shape); the twin works in metres,
kilograms and degrees. Everything is converted here, once, both ways: requests in, in-hand poses out. Nothing on the
Isaac side sees millimetres.
"""

from collections.abc import Sequence

from sim_server.models.finger import FingerDesign
from sim_server.models.grasp import GraspSettings
from sim_server.models.gripper import GripperGeometry
from sim_server.models.offset import Offset
from sim_server.models.outcome import Landing
from sim_server.models.part import Part
from sim_server.models.piece import Piece, Point
from sim_server.models.pose import InHandPose

M_PER_MM = 1e-3
MM_PER_M = 1e3
KG_PER_G = 1e-3
# scene_config.CUBE_JAW_HALF_TARGET closes each jaw 0.3 mm past first contact at the hooked tip ("per-jaw seating travel").
STOCK_SEATING = 0.0003
MIN_PIECE_VOLUME_MM3 = 1e-3  # below this a piece is flat or degenerate and PhysX can't cook a convex hull from it
TABLE_TOLERANCE_MM = 1e-3  # a mesh part's points may dip this far below the table (rounding), no further
IN_HAND_DECIMALS = 4  # 0.1 um and 0.0001 deg: far below what the physics resolves, and it keeps responses small

PiecesMm = Sequence[tuple[Sequence[Sequence[float]], Sequence[Sequence[int]]]]


def part_from_mm(
    shape: str,
    *,
    mass_g: float,
    diameter_mm: float | None = None,
    length_mm: float | None = None,
    axis: str | None = None,
    upright: bool | None = None,
    box_mm: Sequence[float] | None = None,
    pieces_mm: PiecesMm | None = None,
    friction: Sequence[float] | None = None,
) -> Part:
    """Fields that don't apply to the shape are ignored (the app sends all of them). A cylinder's axis defaults to the
    legacy upright flag (true: "z", false: "y"), and to "z" without either.

    A mesh's pieces arrive in the grasp frame (x along the closing direction, origin on the table under the grasp
    centre, z >= 0) and are recentred to mid-height (z - height / 2, height = the highest point), so the part's origin
    is where nominal_pose puts a primitive's centre and the held check works unchanged."""
    if mass_g <= 0:
        raise ValueError("mass_g must be positive")
    common = {"mass": mass_g * KG_PER_G, "friction": None if friction is None else (float(friction[0]), float(friction[1]))}
    if shape == "cylinder":
        if not diameter_mm or not length_mm or diameter_mm <= 0 or length_mm <= 0:
            raise ValueError("a cylinder needs positive diameter_mm and length_mm")
        if axis is None:
            axis = "z" if upright is None or upright else "y"
        d, length = diameter_mm * M_PER_MM, length_mm * M_PER_MM
        sizes = {"z": (d, d, length), "y": (d, length, d), "x": (length, d, d)}
        if axis not in sizes:
            raise ValueError(f"unknown cylinder axis {axis!r}; use 'z', 'y' or 'x'")
        return Part(shape="cylinder", size=sizes[axis], cylinder_axis=axis, **common)
    if shape == "box":
        if box_mm is None or len(box_mm) != 3 or min(box_mm) <= 0:
            raise ValueError("a box needs box_mm = [along the closing direction, across it, height], all positive")
        return Part(shape="box", size=tuple(v * M_PER_MM for v in box_mm), **common)
    if shape == "mesh":
        if not pieces_mm:
            raise ValueError("a mesh part needs its convex pieces")
        pieces = pieces_from_mm("the part", pieces_mm)
        points = [p for piece in pieces for p in piece.points]
        lowest = min(z for _, _, z in points)
        if lowest < -TABLE_TOLERANCE_MM * M_PER_MM:
            raise ValueError(f"the part's pieces reach {-lowest * MM_PER_M:.3f} mm below the table; the grasp frame has the table at z = 0")
        height = max(z for _, _, z in points)
        size = (
            max(x for x, _, _ in points) - min(x for x, _, _ in points),
            max(y for _, y, _ in points) - min(y for _, y, _ in points),
            height,
        )
        centred = tuple(Piece(points=tuple((x, y, z - height / 2) for x, y, z in p.points), triangles=p.triangles) for p in pieces)
        return Part(shape="mesh", size=size, pieces=centred, **common)
    raise ValueError(f"unknown part shape {shape!r}; use 'cylinder', 'box' or 'mesh'")


def piece_volume(points: Sequence[Point], triangles: Sequence[tuple[int, int, int]]) -> float:
    """Signed volume of a closed triangle mesh (positive when the faces point outward)."""
    total = 0.0
    for i, j, k in triangles:
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = points[i], points[j], points[k]
        total += ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)
    return total / 6


def pieces_from_mm(owner: str, pieces_mm: PiecesMm) -> tuple[Piece, ...]:
    """Convex pieces (points in mm, triangles indexing them) to metres, checked the same way for fingers and parts:
    every triangle indexes a real point, and the triangles close a hull with volume. owner names them in errors."""
    pieces = []
    for n, (points, triangles) in enumerate(pieces_mm):
        tris = tuple((int(a), int(b), int(c)) for a, b, c in triangles)
        if any(not 0 <= i < len(points) for t in tris for i in t):
            raise ValueError(f"{owner}, piece {n}: a triangle indexes a point that doesn't exist")
        if abs(piece_volume(points, tris)) < MIN_PIECE_VOLUME_MM3:
            raise ValueError(f"{owner}, piece {n}: zero volume (flat, degenerate, or triangles don't close the hull)")
        pieces.append(Piece(points=tuple((x * M_PER_MM, y * M_PER_MM, z * M_PER_MM) for x, y, z in points), triangles=tris))
    return tuple(pieces)


def design_from_mm(
    design_id: str,
    *,
    pieces_mm: PiecesMm | None = None,
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
    return FingerDesign(
        id=design_id,
        pieces=pieces_from_mm(f"design {design_id!r}", pieces_mm),
        friction=(float(friction[0]), float(friction[1])),
        tip_height=tip,
        jaw_close=jaw,
    )


def offset_from_mm(dx_mm: float, dy_mm: float, yaw_deg: float) -> Offset:
    return Offset(dx=dx_mm * M_PER_MM, dy=dy_mm * M_PER_MM, yaw_deg=float(yaw_deg))


def in_hand_to_mm(pose: InHandPose | None) -> list[float] | None:
    """The response's [dx_mm, dy_mm, dz_mm, tilt_deg, yaw_deg], or None. Yaw stays in (-180, 180] after rounding."""
    if pose is None:
        return None
    values = (pose.dx * MM_PER_M, pose.dy * MM_PER_M, pose.dz * MM_PER_M, pose.tilt_deg, pose.yaw_deg)
    out = [round(v, IN_HAND_DECIMALS) + 0.0 for v in values]  # + 0.0 turns -0.0 into 0.0
    if out[4] <= -180.0:
        out[4] += 360.0
    return out


def landing_to_mm(landing: Landing | None) -> list[float] | None:
    """The response's [shift_mm, turn_deg], or None."""
    if landing is None:
        return None
    shift, turn = landing
    return [round(shift * MM_PER_M, IN_HAND_DECIMALS) + 0.0, round(turn, IN_HAND_DECIMALS) + 0.0]


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
    """Whether the part's nominal width (its extent along the closing direction, a mesh's too) fits between the open
    stock hook tips at all. If not, every grasp fails and isn't simulated (the fingertips would land on top of it)."""
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
