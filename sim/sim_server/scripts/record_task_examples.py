"""Records the example videos for the wizard's task step (docs/notes/frontend-plan.md, step 3): one per task kind, in
Isaac Sim. The twin's stock fingers pick its 10 mm cube at the nominal site with the usual grasp and lift, carry it 0.10 m
along base -Y, and then:

- drop: open over a 60 x 60 mm bin, 25 mm deep (shallow, so the camera sees the cube land), so the cube falls in;
- place: lower it onto a marked square on the table and open;
- insert: lower it into a square socket 0.75 mm wider than the cube on each side, and open so it settles in.

They show what each task means, not any experiment's result: the sim scores the grasp, the lift (and a transport move)
and the part's pose in the hand, not the place or insert themselves (api/models/task.py in the app).

Run it with Isaac's Python on a GPU machine, from the repo root, while no sim server is using the GPU:

    "$ISAAC/python.sh" sim/sim_server/scripts/record_task_examples.py --out runs/task_examples

It writes <out>/<task>.mp4 (H.264, 1280 x 720 by default, about 5-6 MB each; about 10 s per task on the GB10) and logs
each grasp's outcome. Other views go to <task>_<view>.mp4: --views lab overhead side films from the CSI cell's own
cameras (their framing matches the lab's photos, but the cube is a few pixels). --path-tracing 64 renders like the
twin's offline renders (softer shadows, real metal), at about 15 minutes per task and view on the GB10: little to see at
this scale, so the app's videos don't use it.

The app's copies (the defaults: the task view, real-time) are in app/frontend/public/task-examples/, re-encoded for the
web (about 400 KB each) with a still of the result:

    ffmpeg -i <task>.mp4 -c:v libx264 -crf 24 -preset slow -pix_fmt yuv420p -movflags +faststart -an <task>.mp4
    ffmpeg -sseof -0.4 -i <task>.mp4 -frames:v 1 -q:v 3 <task>.jpg

(imageio-ffmpeg's ffmpeg works: python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())".)
"""

import argparse
import logging
import shutil
from pathlib import Path

from sim_server.models.grasp import EnvGrasp
from sim_server.models.recording import PropBox
from sim_server.robot.motion import LIFT_HEIGHT
from sim_server.robot.poses import nominal_pose, true_pose
from sim_server.scene import SceneConfig, load_scene
from sim_server.services.batches import design_from_mm, grasp_settings, offset_from_mm, part_from_mm

logger = logging.getLogger("record_task_examples")

TASKS = ("drop", "place", "insert")
DEST = (0.30, -0.10)  # where every task takes the cube: 0.10 m from the pick along base -Y (the twin puts vials at (0.30, +-0.08))
BIN = (0.060, 0.025, 0.003)  # outer side, height (low, so the camera sees in), wall and floor thickness
TARGET = (0.018, 0.0015, 0.0006)  # the mark's outer side, line width, height
SOCKET = (0.0115, 0.008, 0.006)  # inner side, wall thickness, height
CARRY_S, LOWER_S, RELEASE_S, RISE_S = 1.2, 0.9, 0.5, 0.9
BLUE, GREEN, GREY = (0.20, 0.40, 0.80), (0.10, 0.65, 0.30), (0.25, 0.25, 0.28)
# The camera looks across the jaws (from base +X, so both fingers and the carry along -Y show) and about 35 degrees
# down (into the bin), framing FRAME_WIDTH at a point between the pick and the destination, tall enough for the lift.
EYE_OUT, EYE_UP, AIM_UP, FRAME_WIDTH, APERTURE_MM = 0.42, 0.36, 0.07, 0.34, 20.955
LAB_WIDTH = 0.40  # the lab view's framing, from the overhead camera's position


def props(task: str, surface: float) -> list[PropBox]:
    """The task's scenery at DEST. surface is the work surface's z in the base frame."""
    x, y = DEST
    if task == "drop":
        side, height, wall = BIN
        half, z = side / 2, surface + height / 2
        return [
            PropBox(name="BinFloor", centre=(x, y, surface + wall / 2), size=(side, side, wall), color=BLUE),
            PropBox(name="BinWallNear", centre=(x, y - half + wall / 2, z), size=(side, wall, height), color=BLUE),
            PropBox(name="BinWallFar", centre=(x, y + half - wall / 2, z), size=(side, wall, height), color=BLUE),
            PropBox(name="BinWallLeft", centre=(x - half + wall / 2, y, z), size=(wall, side - 2 * wall, height), color=BLUE),
            PropBox(name="BinWallRight", centre=(x + half - wall / 2, y, z), size=(wall, side - 2 * wall, height), color=BLUE),
        ]
    if task == "place":
        side, line, height = TARGET
        offset, z = (side - line) / 2, surface + height / 2
        return [
            PropBox(name=f"Mark{n}", centre=(x + dx, y + dy, z), size=size, color=GREEN, collide=False)
            for n, (dx, dy, size) in enumerate(
                [
                    (0.0, -offset, (side, line, height)),
                    (0.0, offset, (side, line, height)),
                    (-offset, 0.0, (line, side, height)),
                    (offset, 0.0, (line, side, height)),
                ]
            )
        ]
    inner, wall, height = SOCKET
    offset, z, across = (inner + wall) / 2, surface + height / 2, inner + 2 * wall
    return [
        PropBox(name="SocketNear", centre=(x, y - offset, z), size=(across, wall, height), color=GREY),
        PropBox(name="SocketFar", centre=(x, y + offset, z), size=(across, wall, height), color=GREY),
        PropBox(name="SocketLeft", centre=(x - offset, y, z), size=(wall, inner, height), color=GREY),
        PropBox(name="SocketRight", centre=(x + offset, y, z), size=(wall, inner, height), color=GREY),
    ]


def moves(task: str, surface: float, tip: float, closed: float, opened: float) -> list[tuple]:
    """The moves after the lift, as GraspPlanner.plan_task takes them: fingertip targets in the base frame."""
    x, y = DEST
    up = (x, y, surface + tip + LIFT_HEIGHT)
    carry = ("carry", up, closed, CARRY_S)
    if task == "drop":  # open over the bin; the cube falls in
        return [carry, ("release", None, opened, RELEASE_S), ("rise", (x, y, up[2] + 0.04), opened, RISE_S)]
    if task == "place":  # set it down 1.5 mm above the table, in the mark
        down = (x, y, surface + tip + 0.0015)
    else:  # its bottom 1.5 mm into the socket, the fingertips just above the socket's walls
        down = (x, y, surface + SOCKET[2] - 0.0015 + tip)
    return [carry, ("lower", down, closed, LOWER_S), ("release", None, opened, RELEASE_S), ("rise", up, opened, RISE_S)]


def camera(table_top_z: float, surface: float) -> dict:
    """The view for every task video, as cell.camera() takes it (world coordinates; environment 0 is at the origin)."""
    aim = (DEST[0], DEST[1] / 2, table_top_z + surface + AIM_UP)
    eye = (aim[0] + EYE_OUT, aim[1], table_top_z + surface + EYE_UP)
    reach = ((eye[0] - aim[0]) ** 2 + (eye[2] - aim[2]) ** 2) ** 0.5
    return {
        "eye": eye,
        "look_at": aim,
        "up": (0.0, 0.0, 1.0),
        "focal_length": reach * APERTURE_MM / FRAME_WIDTH,
        "horiz_aperture": APERTURE_MM,
    }


def lab_camera(eye: tuple[float, float, float], table_top_z: float, surface: float) -> dict:
    """From the CSI cell's overhead camera (its eye), zoomed in on the task: LAB_WIDTH framed at the same point as camera()."""
    aim = (DEST[0], DEST[1] / 2, table_top_z + surface + AIM_UP)
    reach = sum((e - a) ** 2 for e, a in zip(eye, aim, strict=True)) ** 0.5
    focal = reach * APERTURE_MM / LAB_WIDTH
    return {"eye": eye, "look_at": aim, "up": (0.0, 0.0, 1.0), "focal_length": focal, "horiz_aperture": APERTURE_MM}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=Path("runs/task_examples"))
    parser.add_argument("--tasks", nargs="+", choices=TASKS, default=list(TASKS))
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument(
        "--views",
        nargs="+",
        choices=("task", "lab", "overhead", "side"),
        default=["task"],
        help="task: the close-up across the jaws; overhead and side: the twin's copies of the CSI cell's own cameras; lab: the "
        "overhead camera's position, zoomed in on the task",
    )
    parser.add_argument(
        "--path-tracing",
        type=int,
        metavar="SPP",
        help="render with path tracing at this many samples per pixel, as the twin's own renders do (render_settings.py)",
    )
    args = parser.parse_args()
    out = args.out.resolve()  # before Isaac starts: Kit changes the working directory
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    scene = load_scene(SceneConfig())
    try:
        import render_settings  # the twin's, like scene_config: importable once load_scene has found it
        import scene_config as C

        if args.path_tracing:
            render_settings.enable_path_tracing(args.path_tracing)

        cell = scene.cell
        geo, planner = cell.geometry, cell.planner
        part = part_from_mm("box", box_mm=[10, 10, 10], mass_g=4)
        design = design_from_mm("stock")
        settings = grasp_settings(design, part, geo)
        pose = true_pose(nominal_pose(part, planner.spread_xy, geo.surface_dz, planner.site_xy), planner.spread_xy, offset_from_mm(0, 0, 0))
        configs = {
            "task": camera(geo.table_top_z, geo.surface_dz),
            "lab": lab_camera(C.TABLE_CAM["eye"], geo.table_top_z, geo.surface_dz),
            "overhead": C.TABLE_CAM,
        }  # side: the cell's own
        for task in args.tasks:
            cell.set_props(props(task, geo.surface_dz))
            plan = planner.plan_task(
                settings.tip_height, settings.jaw_close, moves(task, geo.surface_dz, settings.tip_height, settings.jaw_close, geo.jaw_open)
            )
            folder = out / task
            folder.mkdir(parents=True, exist_ok=True)
            outcome, frames, files = cell.record(
                part, EnvGrasp(design=design, plan=plan, pose=pose), None, args.views, (args.width, args.height), folder, configs
            )
            for view, path in files.items():
                shutil.move(path, out / (f"{task}.mp4" if view == "task" else f"{task}_{view}.mp4"))
            folder.rmdir()
            logger.info("%s: %s after the lift, %d frames of %s", task, "held" if outcome.held else "MISSED", frames, ", ".join(args.views))
    finally:
        scene.close()


if __name__ == "__main__":
    main()
