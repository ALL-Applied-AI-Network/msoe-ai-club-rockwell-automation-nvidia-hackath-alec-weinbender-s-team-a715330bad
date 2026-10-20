"""Grasp-batch routes. Thin: validate the request, convert it through services/batches.py, queue one job per request for the
main thread (sim_queue.py), await it without blocking the event loop, and map exceptions to HTTP errors. No Isaac, no
business rules.

Contract, POST /evaluate_batch (millimetres, grams, degrees; the twin works in metres):

    {"part": {"shape": "cylinder" | "box", "diameter_mm", "length_mm", "upright", "box_mm": [x, y, z], "mass_g"},
     "designs": [{"id": "stock"},
                 {"id", "pieces": [{"points": [[x, y, z], ...], "triangles": [[i, j, k], ...]}, ...],
                  "friction": [static, dynamic], "tip_height_mm", "jaw_close_mm"}, ...],
     "offsets": [{"dx", "dy", "yaw_deg"}, ...]}
    -> {"held": [[bool per offset] per design]}

- part: a cylinder uses diameter_mm and length_mm (along its axis); upright stands it on an end, otherwise it lies with
  its axis across the jaws. A box uses box_mm = [along the jaws' closing direction, across it, height]. Fields that don't
  apply to the shape are ignored. The part rests on the work surface at the nominal grasp site (0.30, 0.0) m in the robot
  base frame, with the twin's part material.
- designs: without "pieces", the twin's stock fingers, grasping like the twin grasps its cubes (tips 2.5 mm above the
  surface, each jaw closed 0.3 mm past where its hook tip meets the part; tip_height_mm / jaw_close_mm override that).
  With "pieces", custom fingers: each piece is the convex hull of its points, in the gripper frame G (see
  robot/gripper_frame.py), describing the finger on JawL with the jaws closed; JawR gets the mirror image. They replace
  both stock fingers' contact geometry. friction is the fingers' [static, dynamic] coefficient (combined with the part's
  0.9 / 0.8 by --friction-combine, average by default). jaw_close_mm is the per-jaw position the jaws close to, 0 =
  closed, 6 = fully open (SMC MHZL2-16D2: 6 mm per jaw). tip_height_mm is how far above the work surface G's origin (the
  stock fingertip plane) stops.
- offsets: camera error, the part's true pose relative to the nominal one, in the gripper's frame at the grasp: dx along
  the closing direction (+ toward JawL), dy across it (G's +y), yaw about the vertical. The robot always plans at the
  nominal pose; every design is tried at every offset.
- held: the part's centre rose more than 25 mm during the lift (the twin's pickup check).

Legacy POST /evaluate {part, design: {template, params}, offsets} -> {successes: [bool, ...]} runs the same path with one
design. Only template "stock" is supported (template params can't be turned into geometry here); others get 501.

Errors: 422 for a request the twin can't run (bad geometry, unreachable grasp), 501 for a non-stock legacy template,
503 while shutting down.
"""

import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from sim_server.dependencies import SceneDep, SimQueueDep
from sim_server.models.batch import GraspBatch
from sim_server.models.grasp import GraspPlanError
from sim_server.scene import Scene
from sim_server.services.batches import design_from_mm, offset_from_mm, part_from_mm
from sim_server.services.evaluations import evaluate_batch
from sim_server.sim_queue import SimQueue, SimQueueClosedError

router = APIRouter(tags=["grasps"])

Positive = Annotated[float, Field(gt=0)]
Coefficient = Annotated[float, Field(ge=0, le=5)]


class PartRequest(BaseModel):
    shape: Literal["cylinder", "box"]
    diameter_mm: Positive | None = None
    length_mm: Positive | None = None
    upright: bool = True
    box_mm: tuple[Positive, Positive, Positive] | None = None  # along the closing direction, across it, height
    mass_g: Positive


class PieceRequest(BaseModel):
    points: list[tuple[float, float, float]] = Field(min_length=4)  # G frame, mm
    triangles: list[tuple[int, int, int]] = Field(min_length=4)  # the hull's outward faces


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


class EvaluateBatchResponse(BaseModel):
    held: list[list[bool]]


class DesignSpec(BaseModel):
    template: str
    params: dict[str, float]


class EvaluateRequest(BaseModel):
    part: PartRequest
    design: DesignSpec
    offsets: list[OffsetRequest]


class EvaluateResponse(BaseModel):
    successes: list[bool]


def to_batch(part: PartRequest, designs: list[DesignRequest], offsets: list[OffsetRequest]) -> GraspBatch:
    """Request (mm, g, deg) -> GraspBatch (m, kg, deg). Raises ValueError for a request the twin can't run."""
    return GraspBatch(
        part=part_from_mm(
            part.shape, mass_g=part.mass_g, diameter_mm=part.diameter_mm, length_mm=part.length_mm, upright=part.upright, box_mm=part.box_mm
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
    )


async def _run(scene: Scene, sim_queue: SimQueue, part: PartRequest, designs: list[DesignRequest], offsets: list[OffsetRequest]):
    try:
        batch = to_batch(part, designs, offsets)
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
    return EvaluateBatchResponse(held=await _run(scene, sim_queue, req.part, req.designs, req.offsets))


@router.post("/evaluate")
async def post_evaluate(req: EvaluateRequest, scene: SceneDep, sim_queue: SimQueueDep) -> EvaluateResponse:
    if req.design.template != "stock":
        raise HTTPException(
            501,
            f"template {req.design.template!r} can't be simulated from its params; send the finger geometry to POST /evaluate_batch "
            "(only template 'stock' works here)",
        )
    held = await _run(scene, sim_queue, req.part, [DesignRequest(id="stock")], req.offsets)
    return EvaluateResponse(successes=held[0])
