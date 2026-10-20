"""The Isaac Sim client: the twin's cell set up for grasp evaluation, as one environment or many copies. The only module
besides scene.py (which starts Isaac) that touches Isaac Sim.

Import only after SimulationApp has started and twin.use_twin() has run (scene.py does both), and call only from the main
thread (sim_queue.py). NOT YET RUN IN ISAAC SIM: written against the Isaac Sim 6.0 core API (isaacsim.core.api,
isaacsim.core.prims); docs/notes/gpu-test-plan.md is how it gets validated. That includes everything contract v2 added:
mesh parts, cylinders along x, the part's own friction material, the grip-force limit, the transport move and the
lift-pose readout behind the in-hand pose.

One environment (the reference path, --envs 1): the twin's own robot (/World/ER4iA) and mat, CPU physics like
sort_scene.py, one grasp at a time. N environments (the vectorised path): N copies of the robot with its gripper and of
the mat, under /World/Envs/Env_i, 2 m apart, each with its own part; normally GPU physics. services/evaluations.py packs a
batch into chunks of one grasp per environment and hands each chunk to run_chunk, which:

1. brings the stage to the chunk's part and fingers, if anything differs: stop the simulation, edit the prims, reset
   (stop + play makes PhysX parse the stage again). A part with other friction is a different part;
2. puts every robot at home with its jaws open, and every part at its true pose, at rest (no stage rebuild), and sets
   the jaw drives' force limit (the batch's grip force, or the twin's 180 N);
3. plays each design's joint trajectory, planned at the nominal pose, on its copies, including the transport move and
   settle when the batch has one;
4. held = the part's centre rose more than 25 mm between the end of the approach and the end of the lift. The part's
   pose at the end of the lift is reported in the base frame (the service turns it into the in-hand pose). Held after
   transport = still more than 25 mm up at the end of the settle.
"""

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cell as twin_cell  # the vendored twin's cell.py, importable through twin.use_twin()
import numpy as np
import omni.usd
import scene_config as C
from isaacsim.core.api import World
from isaacsim.core.prims import Articulation, RigidPrim
from pxr import Gf, PhysxSchema, Sdf, Usd, UsdGeom, UsdPhysics, UsdShade

from sim_server.clients.env_grid import env_origins, slots_to_envs
from sim_server.clients.video import Mp4Writer
from sim_server.models.finger import FingerDesign
from sim_server.models.grasp import EnvGrasp
from sim_server.models.outcome import GraspOutcome
from sim_server.models.part import Part
from sim_server.models.piece import Point
from sim_server.models.pose import BodyPose
from sim_server.robot.gripper_frame import geometry_from_twin, jaw_body_points, jaw_body_triangles
from sim_server.robot.motion import FPS, HELD_RISE, PHYSICS_DT, PHYSICS_STEPS_PER_FRAME, GraspPlanner
from sim_server.robot.poses import nominal_pose, yaw_quaternion

logger = logging.getLogger(__name__)

ENVS_ROOT = "/World/Envs"
MAT_PRIM, TABLE_PRIM = "/World/Mat", "/World/Table"  # where cell.build() puts them
PART_NAME = "Part"
CUSTOM_FINGER = "CustomFinger"
FINGER_MATERIALS = "/World/Physics/CustomFingers"
PART_MATERIAL = "/World/Physics/PartMaterial"
PART_RESTITUTION = 0.05  # the twin's part material (cell.init_physics)
CONTACT_OFFSET = 0.0002  # the twin's sub-millimetre contact offset for the fingers, mat and small parts
REST_OFFSET = 0.0  # likewise (cell.small_contact_offsets)
DEFAULT_PART = Part(shape="box", size=(C.CUBE_EDGE,) * 3, mass=C.CUBE_MASS)  # the stage needs some part before the first batch
FINGER_COLOR, PART_COLOR = (0.95, 0.55, 0.10), (0.85, 0.70, 0.05)
# Recording a grasp (record()). The close-up looks across the jaws' closing direction from the side away from the robot,
# so both fingers show, framing CLOSEUP_WIDTH at the grasp site from CLOSEUP_DISTANCE away, aimed CLOSEUP_AIM_Z above
# the table so the 0.13 m lift stays in frame. The side view is the twin's own side camera.
RECORDING_ROOT = "/World/Recording"
CLOSEUP_DISTANCE, CLOSEUP_WIDTH, CLOSEUP_AIM_Z, CLOSEUP_EYE_Z = 0.35, 0.26, 0.07, 0.08  # metres
APERTURE_MM = 20.955  # the twin's cameras' horizontal aperture
HOLD_FRAMES = 30  # a second after the lift, holding it, so a clip shows whether the part stayed
WARMUP_RENDERS = 30  # before a recording's first frame
# Isaac Lab's PhysxCfg defaults. Isaac's own GPU buffer defaults are sized for small scenes and overflow (with errors
# about found/lost pairs or rigid contacts) once there are many articulations, each with ~150 gripper colliders.
GPU_CAPACITIES = {
    "set_gpu_max_rigid_contact_count": 2**23,
    "set_gpu_max_rigid_patch_count": 5 * 2**15,
    "set_gpu_found_lost_pairs_capacity": 2**21,
    "set_gpu_found_lost_aggregate_pairs_capacity": 2**25,
    "set_gpu_total_aggregate_pairs_capacity": 2**21,
}


@dataclass(frozen=True)
class Env:
    robot: str  # the robot prim (articulation root or its ancestor)
    part: str
    origin: tuple[float, float]  # world XY of this copy's robot base


class GraspCell:
    """Satisfies services/evaluations.Cell: geometry, planner, env_count, run_chunk."""

    def __init__(self, *, envs: int, device: str, env_spacing: float, friction_combine: str):
        if envs < 1:
            raise ValueError("envs must be at least 1")
        self.device, self.gpu = device, device.startswith("cuda")
        self._spacing, self._friction_combine = env_spacing, friction_combine
        # sort_scene.py uses World(stage_units_in_meters=1.0, physics_dt=1 / 60, rendering_dt=1 / 30) on the CPU. A
        # cuda device makes Isaac switch the physics scene to GPU dynamics and the GPU broadphase, suppress USD readback
        # and enable Fabric (SimulationManager.set_device); the views then return torch tensors on that device.
        self.world = World(
            stage_units_in_meters=1.0,
            physics_dt=PHYSICS_DT,
            rendering_dt=1 / 30,
            backend="torch" if self.gpu else "numpy",
            device=device if self.gpu else None,
        )
        self.stage = omni.usd.get_context().get_stage()
        twin_cell.build(self.stage, with_objects=False)  # the cell without the cubes, caps, tubes, fixture and bins
        self.geometry = geometry_from_twin()
        self._check_layout()
        self.planner = GraspPlanner(self.geometry)
        self.envs = self._make_envs(envs)
        self.env_count = len(self.envs)
        self._part: Part | None = None
        self._fingers: list[tuple | None] = [None] * self.env_count  # FingerDesign.finger_key on each env; None = stock
        self._cameras: dict[tuple[str, tuple[int, int]], object] = {}  # (view, size) -> isaacsim Camera, made on first use
        self._arm = self._parts = None
        self._author_parts(DEFAULT_PART)
        if self.gpu:
            self._configure_gpu()
        else:
            twin_cell.enable_ccd(self.world)  # as sort_scene.py does
        self._restart()
        self._description = self._describe_scene()
        logger.info(
            "Grasp cell ready: %d environment(s), device %s, DOFs %s, nominal site %s, jaws close along %s (JawL side); %s",
            self.env_count,
            self.device,
            self._dof_names,
            self.planner.site_xy,
            tuple(round(v, 3) for v in self.planner.spread_xy),
            self._description,
        )

    def describe(self) -> dict:
        """What the cell runs with, for /health and each batch's response. Recorded at startup, so it never touches
        Isaac and is safe to call from the HTTP thread."""
        return dict(self._description)

    def record(
        self, part: Part, grasp: EnvGrasp, grip_force: float | None, views: list[str], size: tuple[int, int], out_dir: Path
    ) -> tuple[GraspOutcome, int, dict[str, str]]:
        """One grasp on environment 0, run exactly as run_chunk runs it, with rendering on: each control frame is read
        from every view's camera and written to out_dir/<view>.mp4, then HOLD_FRAMES more hold the lift so the outcome
        shows. Returns (the outcome, the frame count, view -> mp4 path)."""
        cameras = {view: self._camera(view, size) for view in views}
        writers = {view: Mp4Writer(out_dir / f"{view}.mp4", size, FPS) for view in views}

        def capture() -> None:
            for view, camera in cameras.items():
                rgba = camera.get_rgba()
                if rgba is None or rgba.size == 0:
                    raise RuntimeError(f"the {view} camera returned no image")
                writers[view].write(np.ascontiguousarray(rgba[:, :, :3], dtype=np.uint8).tobytes())

        try:
            [outcome] = self.run_chunk(part, [grasp], grip_force, on_frame=capture, hold_frames=HOLD_FRAMES)
        finally:
            for writer in writers.values():
                writer.close()
        frames = writers[views[0]].frames
        return outcome, frames, {view: str(writer.path) for view, writer in writers.items()}

    def run_chunk(
        self,
        part: Part,
        grasps: list[EnvGrasp],
        grip_force: float | None = None,
        *,
        on_frame: Callable[[], None] | None = None,
        hold_frames: int = 0,
    ) -> list[GraspOutcome]:
        """grasps[e] runs on environment e; the other environments hold home with their part at the nominal pose. Every
        plan in a chunk must have the same segments (a batch has one transport). With on_frame (a recording), the stage
        is rendered once per control frame and on_frame is called after it, and hold_frames more frames hold the last
        target; the outcome is measured at the same frames either way."""
        self._prepare_stage(part, [grasp.design for grasp in grasps])
        n, geo = self.env_count, self.geometry
        nominal = nominal_pose(part, self.planner.spread_xy, geo.surface_dz, self.planner.site_xy)
        plans = [grasp.plan for grasp in grasps] + [None] * (n - len(grasps))
        poses = [grasp.pose for grasp in grasps] + [nominal] * (n - len(grasps))
        first = plans[0]
        if any(plan.segment_end != first.segment_end for plan in plans if plan is not None):
            raise ValueError("the grasps in a chunk follow different segments; a batch has one transport")
        approach_end, lift_end, settle_end = first.segment_end["approach"], first.segment_end["lift"], first.segment_end.get("settle")

        home = self._joint_vector(self.planner.q_home, geo.jaw_open)
        targets = np.tile(home, (first.frames, n, 1))
        jaw_targets: dict[int, np.ndarray] = {}
        for e, plan in enumerate(plans):
            if plan is None:
                continue
            slot = self._arm_slot[e]
            targets[:, slot, self._arm_dofs] = plan.arm
            if id(plan) not in jaw_targets:  # copies of a design share one plan object
                jaw_targets[id(plan)] = np.array([[twin_cell.jaw_targets(j)[joint] for joint in self._jaw_joints] for j in plan.jaw])
            targets[:, slot, self._jaw_dofs] = jaw_targets[id(plan)]

        positions, orientations = np.zeros((n, 3)), np.zeros((n, 4))
        for e, pose in enumerate(poses):
            slot, (ox, oy) = self._part_slot[e], self.envs[e].origin
            x, y, z = pose.position
            positions[slot] = (ox + x, oy + y, geo.table_top_z + z)
            orientations[slot] = yaw_quaternion(pose.yaw_deg)

        # Every grasp starts from rest: robot at home, jaws open, part re-placed with zero velocity.
        homes = np.tile(home, (n, 1))
        self._arm.set_joint_positions(self._tensor(homes))
        self._arm.set_joint_velocities(self._tensor(np.zeros_like(homes)))
        self._arm.set_joint_position_targets(self._tensor(homes))
        self._parts.set_world_poses(self._tensor(positions), self._tensor(orientations))
        self._parts.set_velocities(self._tensor(np.zeros((n, 6))))
        self._set_grip_force(grip_force)

        targets = self._tensor(targets)
        if on_frame is not None:
            for _ in range(WARMUP_RENDERS):  # renders only, no physics: materials compile, and the first images come back empty
                self.world.render()
        z_start = lift = z_settled = None
        for frame in range(first.frames + hold_frames):
            self._arm.set_joint_position_targets(targets[min(frame, first.frames - 1)])
            for step in range(PHYSICS_STEPS_PER_FRAME):
                self.world.step(render=on_frame is not None and step == PHYSICS_STEPS_PER_FRAME - 1)
            if on_frame is not None:
                on_frame()
            if frame + 1 == approach_end:
                z_start = self._part_poses()[0][:, 2]
            if frame + 1 == lift_end:
                lift = self._part_poses()
            if frame + 1 == settle_end:
                z_settled = self._part_poses()[0][:, 2]
        lift_positions, lift_orientations = lift
        rise = lift_positions[:, 2] - z_start
        finite = np.isfinite(rise) & np.all(np.isfinite(lift_positions), axis=1) & np.all(np.isfinite(lift_orientations), axis=1)
        if not np.all(finite):
            logger.warning("%d part(s) have non-finite poses after the lift (physics blew up); counted as dropped", int(np.sum(~finite)))
        risen_after = None if z_settled is None else z_settled - z_start

        outcomes = []
        for e in range(len(grasps)):
            slot, (ox, oy) = self._part_slot[e], self.envs[e].origin
            lift_pose = None
            if finite[slot]:
                x, y, z = lift_positions[slot]
                lift_pose = BodyPose(
                    position=(float(x - ox), float(y - oy), float(z - geo.table_top_z)),  # world -> this copy's base frame
                    orientation=tuple(float(v) for v in lift_orientations[slot]),
                )
            outcomes.append(
                GraspOutcome(
                    held=bool(finite[slot] and rise[slot] > HELD_RISE),
                    lift_pose=lift_pose,
                    held_after_transport=None if risen_after is None else bool(risen_after[slot] > HELD_RISE),  # NaN -> False
                )
            )
        return outcomes

    # ------------------------------------------------------------------ stage

    def _check_layout(self) -> None:
        carriage_x, finger_x = twin_cell.gripper_layout()
        geo = self.geometry
        pairs = ((carriage_x, geo.carriage_x), (finger_x, geo.finger_x), (twin_cell.tip_offset(), geo.tip_offset))
        if not all(math.isclose(a, b, abs_tol=1e-9) for a, b in pairs):
            raise RuntimeError("cell.py's gripper layout no longer matches robot/gripper_frame.geometry_from_twin(); update it")

    def _make_envs(self, n: int) -> list[Env]:
        if n == 1:
            return [Env(C.ROBOT_PRIM, f"/World/{PART_NAME}", (0.0, 0.0))]
        # Copy the robot (with the gripper, jaws and joints attach_gripper added) and the mat into each environment.
        # Sdf.CopySpec re-targets relationships inside the copied subtree (the jaw joints' body0/body1) and leaves the
        # rest (materials under /World/Looks and /World/Physics) shared.
        layer = self.stage.GetEditTarget().GetLayer()
        UsdGeom.Xform.Define(self.stage, ENVS_ROOT)
        robot_name = C.ROBOT_PRIM.rsplit("/", 1)[1]
        envs = []
        for i, (x, y) in enumerate(env_origins(n, self._spacing)):
            root = f"{ENVS_ROOT}/Env_{i}"
            UsdGeom.Xform.Define(self.stage, root).AddTranslateOp().Set(Gf.Vec3d(x, y, 0.0))
            for source in (C.ROBOT_PRIM, MAT_PRIM):
                if not Sdf.CopySpec(layer, source, layer, f"{root}/{source.rsplit('/', 1)[1]}"):
                    raise RuntimeError(f"could not copy {source} into {root}")
            envs.append(Env(f"{root}/{robot_name}", f"{root}/{PART_NAME}", (x, y)))
        for template in (C.ROBOT_PRIM, MAT_PRIM, TABLE_PRIM):
            self.stage.GetPrimAtPath(template).SetActive(False)
        logger.info("Copied the robot and mat into %d environments, %.1f m apart", n, self._spacing)
        return envs

    def _configure_gpu(self) -> None:
        context = self.world.get_physics_context()
        # SimulationManager.set_device("cuda:N") already does these two in Isaac Sim 6.x. Repeat them so an older core
        # can't silently leave the scene on CPU dynamics, and log what the scene ended up with.
        context.enable_gpu_dynamics(True)
        context.set_broadphase_type("GPU")
        for setter, value in GPU_CAPACITIES.items():
            getattr(context, setter)(value)
        logger.info(
            "GPU physics on %s: gpu dynamics %s, broadphase %s, solver %s",
            self.device,
            context.is_gpu_dynamics_enabled(),
            context.get_broadphase_type(),
            context.get_solver_type(),
        )

    def _describe_scene(self) -> dict:
        """The settings a result depends on, read once from the built stage. The first eight keys are the ones the
        backend compares with the cell profile (api/models/cell_profile.SERVER_SIM_KEYS); the rest are for the record.

        solver_*_iterations are the part body's (cell.make_dynamic authors 16 / 2), which is what the profile describes;
        the robot articulation's are under robot_solver_iterations. Both are the authored values, None where the USD
        leaves PhysX's default. contact_offset_mm and rest_offset_mm are what the part's and the custom fingers'
        colliders get (the twin's small_contact_offsets: 0.2 mm and 0)."""
        robot_root = next(
            (prim for prim in Usd.PrimRange(self.stage.GetPrimAtPath(self.envs[0].robot)) if prim.HasAPI(UsdPhysics.ArticulationRootAPI)),
            None,
        )
        robot = PhysxSchema.PhysxArticulationAPI(robot_root) if robot_root is not None else None
        part = PhysxSchema.PhysxRigidBodyAPI(self.stage.GetPrimAtPath(self.envs[0].part))
        return {
            "envs": self.env_count,
            "device": self.device,
            "friction_combine": self._friction_combine,
            "physics_dt": PHYSICS_DT,  # seconds
            "solver_position_iterations": _authored(part.GetSolverPositionIterationCountAttr()),
            "solver_velocity_iterations": _authored(part.GetSolverVelocityIterationCountAttr()),
            "contact_offset_mm": round(CONTACT_OFFSET * 1000, 6),
            "rest_offset_mm": round(REST_OFFSET * 1000, 6),
            "physics_steps_per_frame": PHYSICS_STEPS_PER_FRAME,
            "control_fps": FPS,
            "solver_type": self.world.get_physics_context().get_solver_type(),
            "robot_solver_iterations": {
                "position": _authored(robot.GetSolverPositionIterationCountAttr()) if robot else None,
                "velocity": _authored(robot.GetSolverVelocityIterationCountAttr()) if robot else None,
            },
            "jaw_max_force_n": C.JAW_MAX_FORCE,
            "nominal_site_xy": list(self.planner.site_xy),
        }

    def _prepare_stage(self, part: Part, designs: list[FingerDesign]) -> None:
        """Brings the stage to this part and these fingers (designs[e] on environment e; the rest keep theirs). Edits
        happen with the simulation stopped, then a reset makes PhysX parse the stage again."""
        changed = [e for e, design in enumerate(designs) if design.finger_key != self._fingers[e]]
        new_part = part != self._part
        if not new_part and not changed:
            return
        started = time.perf_counter()
        self.world.stop()
        if new_part:
            self._author_parts(part)
        for e in changed:
            self._author_fingers(e, designs[e])
        self._restart()
        logger.info(
            "Stage edit (%s%d finger swap(s)) and physics re-parse: %.1f s",
            "new part, " if new_part else "",
            len(changed),
            time.perf_counter() - started,
        )

    def _author_parts(self, part: Part) -> None:
        """Every copy's part: one rigid body whose "Collider" child is a primitive (box, cylinder along z, y or x) or, for
        a mesh, an Xform with one convex-hull Mesh per piece. All colliders get the part's material."""
        nominal = nominal_pose(part, self.planner.spread_xy, self.geometry.surface_dz, self.planner.site_xy)
        x, y, z = nominal.position
        material = self._part_material(part.friction)
        for env in self.envs:
            body = self.stage.GetPrimAtPath(env.part)
            if not body.IsValid():
                body = UsdGeom.Xform.Define(self.stage, env.part).GetPrim()
                xform = UsdGeom.Xformable(body)
                xform.AddTranslateOp()
                xform.AddOrientOp()
                twin_cell.make_dynamic(body, part.mass, collide_self=False)  # the twin's damping, solver iterations, material
            UsdPhysics.MassAPI(body).GetMassAttr().Set(part.mass)
            translate, orient = UsdGeom.Xformable(body).GetOrderedXformOps()
            translate.Set(Gf.Vec3d(x, y, z + self.geometry.table_top_z))  # relative to the environment's origin
            orient.Set(Gf.Quatf(*yaw_quaternion(nominal.yaw_deg)))
            # Swap only the collider child: removing the body itself would invalidate the parts view.
            path = f"{env.part}/Collider"
            if self.stage.GetPrimAtPath(path).IsValid():
                self.stage.RemovePrim(path)
            if part.shape == "mesh":
                UsdGeom.Xform.Define(self.stage, path)
                for n, piece in enumerate(part.pieces):  # points are already in the body's frame (models/part.py)
                    self._author_convex_piece(f"{path}/Piece{n:02d}", piece.points, piece.triangles, PART_COLOR, material)
                continue
            if part.shape == "box":
                geom = UsdGeom.Cube.Define(self.stage, path)
                geom.CreateSizeAttr(1.0)
                UsdGeom.Xformable(geom).AddScaleOp().Set(Gf.Vec3f(*part.size))
            else:
                geom = UsdGeom.Cylinder.Define(self.stage, path)
                geom.CreateAxisAttr(part.cylinder_axis.upper())
                geom.CreateRadiusAttr(part.diameter / 2)
                geom.CreateHeightAttr(part.length)
            geom.CreateDisplayColorAttr([Gf.Vec3f(*PART_COLOR)])
            UsdPhysics.CollisionAPI.Apply(geom.GetPrim())
            twin_cell.bind_physics_material(geom.GetPrim(), material)
            twin_cell.small_contact_offsets(geom.GetPrim())
        self._part = part

    def _author_fingers(self, e: int, design: FingerDesign) -> None:
        """Stock: the twin's contact prisms and visuals. Custom: the design's convex pieces on both jaws (JawR mirrored),
        with the stock prisms deactivated and the stock visual hidden. Jaw bodies, joints and drives stay as they are."""
        env = self.envs[e]
        material = None if design.is_stock else self._finger_material(e, design.friction)
        for side, tag in ((+1, "L"), (-1, "R")):
            jaw = env.robot + twin_cell.JAW_PRIMS[tag][len(C.ROBOT_PRIM) :]
            stock_collision = self.stage.GetPrimAtPath(f"{jaw}/Collision")
            if not stock_collision.IsValid():
                raise RuntimeError(f"{jaw}/Collision not found; cell.attach_gripper changed")
            custom = f"{jaw}/{CUSTOM_FINGER}"
            if self.stage.GetPrimAtPath(custom).IsValid():
                self.stage.RemovePrim(custom)
            stock_collision.SetActive(design.is_stock)
            UsdGeom.Imageable(self.stage.GetPrimAtPath(f"{jaw}/Detail")).CreateVisibilityAttr().Set(
                UsdGeom.Tokens.inherited if design.is_stock else UsdGeom.Tokens.invisible
            )
            if design.is_stock:
                continue
            UsdGeom.Xform.Define(self.stage, custom)
            for n, piece in enumerate(design.pieces):
                points = jaw_body_points(piece.points, side, self.geometry)
                self._author_convex_piece(
                    f"{custom}/Piece{n:02d}", points, jaw_body_triangles(piece.triangles, side), FINGER_COLOR, material
                )
        self._fingers[e] = design.finger_key

    def _author_convex_piece(
        self, path: str, points: list[Point], triangles: list[tuple[int, int, int]], color: tuple[float, float, float], material: str
    ) -> None:
        """One convex collider, treated like the twin's finger prisms: convex-hull approximation, sub-millimetre contact
        offsets, and a physics material. Used for custom finger pieces and mesh-part pieces alike."""
        mesh = UsdGeom.Mesh.Define(self.stage, path)
        mesh.CreatePointsAttr([Gf.Vec3f(*p) for p in points])
        mesh.CreateFaceVertexCountsAttr([3] * len(triangles))
        mesh.CreateFaceVertexIndicesAttr([i for triangle in triangles for i in triangle])
        mesh.CreateSubdivisionSchemeAttr("none")
        mesh.CreateDisplayColorAttr([Gf.Vec3f(*color)])
        prim = mesh.GetPrim()
        UsdPhysics.CollisionAPI.Apply(prim)
        UsdPhysics.MeshCollisionAPI.Apply(prim).CreateApproximationAttr().Set("convexHull")
        contact = PhysxSchema.PhysxCollisionAPI.Apply(prim)
        contact.CreateContactOffsetAttr().Set(CONTACT_OFFSET)
        contact.CreateRestOffsetAttr().Set(REST_OFFSET)
        twin_cell.bind_physics_material(prim, material)

    def _finger_material(self, e: int, friction: tuple[float, float]) -> str:
        """One material per environment, rewritten when its fingers change, so materials don't pile up over a long run.
        PhysX combines it with the part's material using friction_combine."""
        return self._physics_material(f"{FINGER_MATERIALS}/Env{e:04d}", friction, restitution=0.0)

    def _part_material(self, friction: tuple[float, float] | None) -> str:
        """None: the twin's part material (cell.PHYS_MAT_PATH, 0.9 / 0.8), exactly as before contract v2. Otherwise one
        material shared by every copy's part, rewritten when the part changes, with the server's friction combine mode
        (PhysX uses the higher-priority mode of the two materials in a contact, so the fingers' and the part's agree)."""
        if friction is None:
            return twin_cell.PHYS_MAT_PATH
        return self._physics_material(PART_MATERIAL, friction, restitution=PART_RESTITUTION)

    def _physics_material(self, path: str, friction: tuple[float, float], restitution: float) -> str:
        material = UsdShade.Material.Define(self.stage, path).GetPrim()
        api = UsdPhysics.MaterialAPI.Apply(material)
        api.CreateStaticFrictionAttr().Set(float(friction[0]))
        api.CreateDynamicFrictionAttr().Set(float(friction[1]))
        api.CreateRestitutionAttr().Set(float(restitution))
        PhysxSchema.PhysxMaterialAPI.Apply(material).CreateFrictionCombineModeAttr().Set(self._friction_combine)
        return path

    def _restart(self) -> None:
        """Reset (stop + play, which re-parses physics), then fresh views. Views are rebuilt rather than trusted to
        re-initialise themselves, and environments are matched to view slots by where their bodies are."""
        for view in (self._arm, self._parts):
            if view is not None:
                view.destroy()
        self.world.reset()
        self.world.step(render=False)  # one step so the GPU pipeline has published body poses before we read them
        many = self.env_count > 1
        robot_expr = f"{ENVS_ROOT}/Env_.*/{C.ROBOT_PRIM.rsplit('/', 1)[1]}" if many else C.ROBOT_PRIM
        self._arm = Articulation(prim_paths_expr=robot_expr, name="er4ia", reset_xform_properties=False)
        self._arm.initialize()
        self._parts = RigidPrim(
            prim_paths_expr=f"{ENVS_ROOT}/Env_.*/{PART_NAME}" if many else self.envs[0].part,
            name="parts",
            reset_xform_properties=False,
            prepare_contact_sensors=False,
        )
        self._parts.initialize()
        self._dof_names = list(self._arm.dof_names)
        self._jaw_joints = list(twin_cell.JAW_JOINTS.values())
        missing = [name for name in [f"J{i}" for i in range(1, 7)] + self._jaw_joints if name not in self._dof_names]
        if missing:
            raise RuntimeError(f"articulation DOFs {self._dof_names} lack {missing}")
        self._arm_dofs = [self._dof_names.index(f"J{i}") for i in range(1, 7)]
        self._jaw_dofs = [self._dof_names.index(joint) for joint in self._jaw_joints]
        if many:
            origins = [env.origin for env in self.envs]
            site = np.array(self.planner.site_xy)
            arm_env = slots_to_envs(self._numpy(self._arm.get_world_poses()[0])[:, :2], origins, self._spacing / 2)
            part_env = slots_to_envs(self._numpy(self._parts.get_world_poses()[0])[:, :2] - site, origins, self._spacing / 2)
        else:
            arm_env = part_env = [0]
        self._arm_slot = {env: slot for slot, env in enumerate(arm_env)}
        self._part_slot = {env: slot for slot, env in enumerate(part_env)}

    # ------------------------------------------------------------------ recording

    def _camera(self, view: str, size: tuple[int, int]):
        """The view's camera at this size, made on first use and kept: each camera is a render product, so making one per
        recording would pile them up."""
        key = (view, size)
        if key not in self._cameras:
            from isaacsim.sensors.camera import Camera  # rendering only; a batch never needs it

            path = f"{RECORDING_ROOT}/{view.capitalize()}_{size[0]}x{size[1]}"
            twin_cell.camera(self.stage, path, self._camera_config(view, size))
            camera = Camera(prim_path=path, resolution=size)
            camera.initialize()
            self._cameras[key] = camera
            logger.info("Recording camera %s at %dx%d ready", view, *size)
        return self._cameras[key]

    def _camera_config(self, view: str, size: tuple[int, int]) -> dict:
        """Where a view's camera sits, as cell.camera() takes it, relative to environment 0 (the record() grasp's)."""
        ox, oy = self.envs[0].origin
        if view == "side":
            eye, look_at = ((x + ox, y + oy, z) for x, y, z in (C.SIDE_CAM["eye"], C.SIDE_CAM["look_at"]))
            return {**C.SIDE_CAM, "eye": eye, "look_at": look_at, "resolution": size}
        (sx, sy), (dx, dy) = self.planner.site_xy, self.planner.spread_xy
        across = (-dy, dx) if -dy * sx + dx * sy >= 0 else (dy, -dx)  # perpendicular to the closing direction, away from the base
        top = self.geometry.table_top_z
        aim = (ox + sx, oy + sy, top + CLOSEUP_AIM_Z)
        return {
            "eye": (aim[0] + across[0] * CLOSEUP_DISTANCE, aim[1] + across[1] * CLOSEUP_DISTANCE, top + CLOSEUP_EYE_Z),
            "look_at": aim,
            "up": (0.0, 0.0, 1.0),
            "focal_length": CLOSEUP_DISTANCE * APERTURE_MM / CLOSEUP_WIDTH,
            "horiz_aperture": APERTURE_MM,
            "resolution": size,
        }

    # ------------------------------------------------------------------ tensors

    def _set_grip_force(self, grip_force: float | None) -> None:
        """The jaw drives' force limit on every copy: the batch's grip force, or the twin's JAW_MAX_FORCE (180 N), so a
        batch without one never inherits the previous batch's. Only the jaw DOFs; the arm's limits stay as authored.

        Set before the chunk, so it also limits the close: the limit caps the whole drive force, damping included
        (JAW_DRIVE_DAMP, 3e3 N s/m), so the jaws close at most F / 3000 m/s. A low limit may not reach the part before
        the lift (docs/notes/gpu-test-plan.md, stage 5.4); if the GPU run shows that, apply it from the end of "close"."""
        force = C.JAW_MAX_FORCE if grip_force is None else float(grip_force)
        values = np.full((self.env_count, len(self._jaw_dofs)), force)
        self._arm.set_max_efforts(self._tensor(values), joint_indices=list(self._jaw_dofs))

    def _joint_vector(self, q_arm: np.ndarray, jaw: float) -> np.ndarray:
        full = np.zeros(len(self._dof_names))
        full[self._arm_dofs] = q_arm
        for joint, value in twin_cell.jaw_targets(jaw).items():
            full[self._dof_names.index(joint)] = value
        return full

    def _part_poses(self) -> tuple[np.ndarray, np.ndarray]:
        """World positions (n, 3) and (w, x, y, z) orientations (n, 4) of the parts, by view slot."""
        positions, orientations = self._parts.get_world_poses()
        return self._numpy(positions).astype(float), self._numpy(orientations).astype(float)

    def _tensor(self, array: np.ndarray):
        if self.gpu:
            import torch

            return torch.as_tensor(np.asarray(array, dtype=np.float32), device=self.device)
        return np.asarray(array, dtype=np.float32)

    @staticmethod
    def _numpy(values) -> np.ndarray:
        return values.detach().cpu().numpy() if hasattr(values, "detach") else np.asarray(values)


def _authored(attribute) -> int | None:
    """An attribute's value, or None when the schema isn't applied (the attribute doesn't exist)."""
    return attribute.Get() if attribute else None
