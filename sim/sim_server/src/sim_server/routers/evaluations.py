"""Grasp-batch routes. Thin: validate the request, convert it through services/batches.py, queue one job per request for the
main thread (sim_queue.py), await it without blocking the event loop, and map exceptions to HTTP errors. No Isaac, no
business rules.

Contract v2, POST /evaluate_batch (millimetres, grams, degrees, newtons; the twin works in metres):

    {"part": {"shape": "cylinder" | "box" | "mesh", "diameter_mm", "length_mm", "axis": "z" | "y" | "x",
              "box_mm": [x, y, z], "pieces": [{"points": [[x, y, z], ...], "triangles": [[i, j, k], ...]}, ...],
              "mass_g", "friction": [static, dynamic] | null},
     "designs": [{"id": "stock"},
                 {"id", "pieces": [{"points": [[x, y, z], ...], "triangles": [[i, j, k], ...]}, ...],
                  "friction": [static, dynamic], "tip_height_mm", "jaw_close_mm"}, ...],
     "offsets": [{"dx", "dy", "yaw_deg"}, ...],
     "grip_force_n": float | null,
     "transport": null | "slow" | "normal" | "fast"}
    -> {"held": [[bool per offset] per design],
        "in_hand": [[[dx_mm, dy_mm, dz_mm, tilt_deg, yaw_deg] | null per offset] per design],
        "held_after_transport": [[bool per offset] per design] | null,
        "sim": {"envs", "device", "friction_combine", "physics_dt", "solver_position_iterations",
                "solver_velocity_iterations", "contact_offset_mm", "rest_offset_mm", ...}}

- part: the part as the gripper meets it, in the grasp frame: x along the jaws' closing direction (toward JawL), y across
  it, z up. Fields that don't apply to the shape are ignored.
  - cylinder: diameter_mm and length_mm (along its axis). axis "z" stands it on an end, "y" lays it across the jaws, "x"
    lays it along them (the jaws grip its end faces). Without axis, the legacy "upright" flag picks "z" (true, the
    default) or "y" (false).
  - box: box_mm = [along the closing direction, across it, height].
  - mesh: pieces, convex like a finger's and validated the same way, with the origin on the table under the grasp centre
    (every point has z >= 0). One rigid body with a convex-hull collider per piece; its width for the stock-fit check is
    its extent along x.
  - friction: the part's physics material, [static, dynamic]; null keeps the twin's part material (0.9 / 0.8). Custom
    fingers' friction combines with it by --friction-combine (average by default), so sending the same pair on the part
    and the fingers gives exactly that pair under every mode but multiply.
  The part rests on the work surface at the nominal grasp site (0.30, 0.0) m in the robot base frame.
- designs: without "pieces", the twin's stock fingers, grasping like the twin grasps its cubes (tips 2.5 mm above the
  surface, each jaw closed 0.3 mm past where its hook tip meets the part; tip_height_mm / jaw_close_mm override that).
  With "pieces", custom fingers: each piece is the convex hull of its points, in the gripper frame G (see
  robot/gripper_frame.py), describing the finger on JawL with the jaws closed; JawR gets the mirror image. They replace
  both stock fingers' contact geometry. friction is the fingers' [static, dynamic] coefficient. jaw_close_mm is the
  per-jaw position the jaws close to, 0 = closed, 6 = fully open (SMC MHZL2-16D2: 6 mm per jaw). tip_height_mm is how
  far above the work surface G's origin (the stock fingertip plane) stops.
- offsets: camera error, the part's true pose relative to the nominal one, in the gripper's frame at the grasp: dx along
  the closing direction (+ toward JawL), dy across it (G's +y), yaw about the vertical. The robot always plans at the
  nominal pose; every design is tried at every offset.
- grip_force_n: the per-jaw force limit on the jaw drive; null keeps the twin's 180 N. The drive is a stiff position
  servo, so it only bites when the limit is below what the servo would push with.
- transport: after the lift, carry the part 0.12 m along base +X (across the jaws) in 1.2, 0.6 or 0.3 s, then hold
  0.5 s. null: no move.
- held: the part's centre rose more than 25 mm during the lift (the twin's pickup check).
- in_hand: where the part sits at the end of the lift, in the commanded gripper frame G, minus where a perfectly centred
  part would sit (0, 0, height / 2 - tip height): dx, dy, dz in mm, tilt (its z axis vs G's) and yaw (its x axis about
  G's z, from G's x, in (-180, 180]) in degrees. A cylinder's angles follow its own axis, so a roll about it reads zero:
  standing, its lean and yaw 0; lying, its axis's angle out of G's xy plane and its turn about G's z, in (-90, 90].
  null where the part wasn't held or the grasp wasn't simulated.
- held_after_transport: still more than 25 mm up at the end of the settle; null when transport is null.
- sim: the scene's description, for the caller's run metadata: envs, device, friction_combine, physics_dt (seconds),
  the part body's solver_position_iterations and solver_velocity_iterations, the colliders' contact_offset_mm and
  rest_offset_mm (the keys the backend compares with its cell profile), plus extras such as solver_type and
  robot_solver_iterations.

Legacy POST /evaluate {part, design: {template, params}, offsets} -> {successes: [bool, ...]} runs the same path with one
design and returns held only. Only template "stock" is supported (template params can't be turned into geometry here);
others get 501.

Errors: 422 for a request the twin can't run (bad geometry, unreachable grasp), 501 for a non-stock legacy template,
503 while shutting down.
"""

import asyncio
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from sim_server.dependencies import SceneDep, SimQueueDep
from sim_server.models.batch import GraspBatch
from sim_server.models.grasp import GraspPlanError, Transport
from sim_server.models.outcome import BatchOutcome
from sim_server.scene import Scene
from sim_server.services.batches import design_from_mm, in_hand_to_mm, offset_from_mm, part_from_mm
from sim_server.services.evaluations import evaluate_batch
from sim_server.sim_queue import SimQueue, SimQueueClosedError

router = APIRouter(tags=["grasps"])

Positive = Annotated[float, Field(gt=0)]
Coefficient = Annotated[float, Field(ge=0, le=5)]


class PieceRequest(BaseModel):
    points: list[tuple[float, float, float]] = Field(min_length=4)  # mm: G for a finger, the grasp frame for a part
    triangles: list[tuple[int, int, int]] = Field(min_length=4)  # the hull's outward faces


class PartRequest(BaseModel):
    shape: Literal["cylinder", "box", "mesh"]
    diameter_mm: Positive | None = None
    length_mm: Positive | None = None
    axis: Literal["z", "y", "x"] | None = None  # cylinder; None: from upright
    upright: bool | None = None  # legacy: true = axis "z", false = axis "y"; ignored when axis is given
    box_mm: tuple[Positive, Positive, Positive] | None = None  # along the closing direction, across it, height
    pieces: list[PieceRequest] | None = None  # mesh: grasp frame, z >= 0
    mass_g: Positive
    friction: tuple[Coefficient, Coefficient] | None = None  # None: the twin's part material


class DesignRequest(BaseModel):
    id: str
    pieces: list[PieceRequest] | None = None  # None: the twin's stock fingers
    friction: tuple[Coefficient, Coefficient] | None = None
    tip_height_mm: Annotated[float, Field(ge=0, le=100)] | None = None
    jaw_close_mm: Annotated[float, Field(ge=0, le=6)] | None = None  # 6 mm stroke per jaw


class OffsetRequest(BaseModel):
    dx: Annotated[float, Field(ge=-50, le=50)]  # mm
    dy: Annotated[float, Field(ge=-50, le=50)]  # mm
    yaw_deg: Annotated[float, Field(ge=-180, le=180)]


class EvaluateBatchRequest(BaseModel):
    part: PartRequest
    designs: list[DesignRequest] = Field(min_length=1)
    offsets: list[OffsetRequest]
    grip_force_n: Positive | None = None  # per jaw; None: the twin's 180 N
    transport: Transport | None = None


class EvaluateBatchResponse(BaseModel):
    held: list[list[bool]]
    in_hand: list[list[list[float] | None]]  # [dx_mm, dy_mm, dz_mm, tilt_deg, yaw_deg]
    held_after_transport: list[list[bool]] | None
    sim: dict[str, Any]


class DesignSpec(BaseModel):
    template: str
    params: dict[str, float]


class EvaluateRequest(BaseModel):
    part: PartRequest
    design: DesignSpec
    offsets: list[OffsetRequest]


class EvaluateResponse(BaseModel):
    successes: list[bool]


def to_batch(
    part: PartRequest,
    designs: list[DesignRequest],
    offsets: list[OffsetRequest],
    grip_force_n: float | None = None,
    transport: Transport | None = None,
) -> GraspBatch:
    """Request (mm, g, deg) -> GraspBatch (m, kg, deg). Raises ValueError for a request the twin can't run."""
    return GraspBatch(
        part=part_from_mm(
            part.shape,
            mass_g=part.mass_g,
            diameter_mm=part.diameter_mm,
            length_mm=part.length_mm,
            axis=part.axis,
            upright=part.upright,
            box_mm=part.box_mm,
            pieces_mm=None if part.pieces is None else [(p.points, p.triangles) for p in part.pieces],
            friction=part.friction,
        ),
        designs=tuple(
            design_from_mm(
                d.id,
                pieces_mm=None if d.pieces is None else [(p.points, p.triangles) for p in d.pieces],
                friction=d.friction,
                tip_height_mm=d.tip_height_mm,
                jaw_close_mm=d.jaw_close_mm,
            )
            for d in designs
        ),
        offsets=tuple(offset_from_mm(o.dx, o.dy, o.yaw_deg) for o in offsets),
        grip_force=grip_force_n,
        transport=transport,
    )


async def _run(scene: Scene, sim_queue: SimQueue, batch_from_request) -> BatchOutcome:
    try:
        batch = batch_from_request()
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    future = sim_queue.submit(evaluate_batch, scene.cell, batch)  # one queue job per request, run on the main thread
    try:
        return await asyncio.wrap_future(future)
    except GraspPlanError as e:
        raise HTTPException(422, str(e)) from e
    except NotImplementedError as e:
        raise HTTPException(501, str(e)) from e
    except SimQueueClosedError as e:
        raise HTTPException(503, str(e)) from e


@router.post("/evaluate_batch")
async def post_evaluate_batch(req: EvaluateBatchRequest, scene: SceneDep, sim_queue: SimQueueDep) -> EvaluateBatchResponse:
    outcome = await _run(scene, sim_queue, lambda: to_batch(req.part, req.designs, req.offsets, req.grip_force_n, req.transport))
    return EvaluateBatchResponse(
        held=[list(row) for row in outcome.held],
        in_hand=[[in_hand_to_mm(pose) for pose in row] for row in outcome.in_hand],
        held_after_transport=None if outcome.held_after_transport is None else [list(row) for row in outcome.held_after_transport],
        sim=scene.describe(),
    )


@router.post("/evaluate")
async def post_evaluate(req: EvaluateRequest, scene: SceneDep, sim_queue: SimQueueDep) -> EvaluateResponse:
    if req.design.template != "stock":
        raise HTTPException(
            501,
            f"template {req.design.template!r} can't be simulated from its params; send the finger geometry to POST /evaluate_batch "
            "(only template 'stock' works here)",
        )
    outcome = await _run(scene, sim_queue, lambda: to_batch(req.part, [DesignRequest(id="stock")], req.offsets))
    return EvaluateResponse(successes=list(outcome.held[0]))
