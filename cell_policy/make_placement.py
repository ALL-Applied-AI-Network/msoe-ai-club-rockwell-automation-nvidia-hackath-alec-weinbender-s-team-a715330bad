"""Write submission/placement.yaml for a test-plan run on the real cell: the same part (an M6 screw or the 16 mm cube) and
bin pose every rollout, and each rollout's prompt tagged with the grasp offset policy.py should command (see policy.py's
docstring).

    python make_placement.py --offsets "0,0,0; 3,0,0; -3,0,0" -o submission/placement.yaml
    python make_placement.py --test-plan plan.json --design D1 --first 10 -o submission/placement.yaml
    python make_placement.py --part cube --tip 2.5 -o submission/placement.yaml

--test-plan reads the app's test plan as JSON (GET /api/jobs/{job_id}/test-plans/{plan_id}, or a list of its rows): each
row's trial_id, offset_x_mm, offset_y_mm and yaw_deg. --tip is the fingertips' height above the surface when they close:
give the height the sim gripped the design at (its tip_height_mm), so the arm repeats the sim's grasp. Standard library
only, so it runs under any Python 3.10+.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

TASKS = {"screw": "Put the screw into the yellow bin.", "cube": "Put the 16 mm cube into the yellow bin."}
TASK = TASKS["screw"]
OBJECT_NAMES = {"screw": "screw", "cube": "cube_16mm"}  # the part's name in placement.yaml, for the operator
DEFAULT_SCREW = (420.0, -40.0, 90.0)  # head x, y (mm, robot frame) and yaw (deg, head to tip): keep policy.py's in step
DEFAULT_CUBE = (420.0, -40.0, 0.0)  # centre x, y (mm) and yaw (deg, a face's normal): keep policy.py's in step
DEFAULT_BIN = (480.0, 120.0, 0.0)
# Ten offsets across the jaws (dx, mm), where the fingers' design matters most: the shank is 6 mm in a 12 mm opening.
DEFAULT_SWEEP = [(0, 0, 0), (1.5, 0, 0), (-1.5, 0, 0), (3, 0, 0), (-3, 0, 0), (4.5, 0, 0), (-4.5, 0, 0), (6, 0, 0), (-6, 0, 0), (0, 0, 0)]
# Ten offsets for the cube: along the jaws only as far as CUBE_MAX_DX_MM, and across them and in yaw, where a miss is a
# slip, not a finger coming down on the cube. All are points of the sim's final grid (yaw layers at 0 and 1.5 x the
# typical 8 deg), so every rollout has a prediction.
DEFAULT_CUBE_SWEEP = [(0, 0, 0), (2, 0, 0), (-2, 0, 0), (4, 0, 0), (-4, 0, 0), (0, 4, 0), (0, -4, 0), (0, 0, 12), (0, 0, -12), (0, 0, 0)]
# Past this along the jaws, a cube finger (EXP-0006's D1: 5.5 mm of slack a side) may come down on the cube's top once
# the operator's placement error adds on: a 16 mm part pressed into the table, not knocked aside like a screw.
CUBE_MAX_DX_MM = 4.5
MIN_TIP_MM = 1.1  # the cell refuses the TCP below z -334 mm (UF0), and the surface is at about -335.1
REACH_MM = 540.0
X_RANGE_MM = (150.0, 650.0)
MIN_SCREW_TO_BIN_MM = 50.0


def numbers(values, sep: str = ",") -> str:
    return sep.join(f"{v:g}" for v in values)


def tag(trial: str, dx: float, dy: float, dyaw: float, part, bin_, kind: str = "screw", tip: float | None = None) -> str:
    """The prompt tag policy.py parses."""
    text = f"[c2f trial={trial} dx={dx:+.2f} dy={dy:+.2f} dyaw={dyaw:+.1f} {kind}={numbers(part)} bin={numbers(bin_)}"
    return text + (f" tip={tip:g}]" if tip is not None else "]")


def rows_from_plan(path: Path, design: str | None, first: int | None, trials: list[str] | None) -> list[tuple[str, float, float, float]]:
    data = json.loads(path.read_text())
    rows = data["rows"] if isinstance(data, dict) else data
    if design:
        rows = [r for r in rows if r["design_label"] == design]
    if trials:
        wanted = {t: i for i, t in enumerate(trials)}
        rows = sorted((r for r in rows if r["trial_id"] in wanted), key=lambda r: wanted[r["trial_id"]])
        missing = set(trials) - {r["trial_id"] for r in rows}
        if missing:
            raise SystemExit(f"not in the test plan: {', '.join(sorted(missing))}")
    if first:
        rows = rows[:first]
    return [(r["trial_id"], float(r["offset_x_mm"]), float(r["offset_y_mm"]), float(r["yaw_deg"])) for r in rows]


def rows_from_offsets(text: str) -> list[tuple[str, float, float, float]]:
    out = []
    for i, item in enumerate(filter(None, (s.strip() for s in text.split(";"))), 1):
        values = [float(v) for v in item.split(",")]
        if not 2 <= len(values) <= 3:
            raise SystemExit(f"an offset is dx,dy or dx,dy,dyaw: {item!r}")
        dx, dy, dyaw = (*values, 0.0)[:3]
        out.append((f"R{i:02d}", dx, dy, dyaw))
    return out


def check_layout(part, bin_, kind: str = "screw") -> list[str]:
    problems = []
    for name, (x, y, *_) in ((kind, part), ("bin", bin_)):
        if math.hypot(x, y) > REACH_MM:
            problems.append(f"the {name} is {math.hypot(x, y):.0f} mm from the base axis, past {REACH_MM:g} mm")
        if not X_RANGE_MM[0] <= x <= X_RANGE_MM[1]:
            problems.append(f"the {name}'s x {x:g} mm is outside {X_RANGE_MM[0]:g}..{X_RANGE_MM[1]:g} mm")
    if math.hypot(part[0] - bin_[0], part[1] - bin_[1]) < MIN_SCREW_TO_BIN_MM:
        problems.append(f"the {kind} is too close to the bin")
    return problems


def check_rollouts(rows, kind: str, tip: float | None) -> list[str]:
    """Grasps the cell would refuse, or that could press a finger into the cube."""
    problems = []
    if tip is not None and tip < MIN_TIP_MM:
        problems.append(f"fingertips {tip:g} mm above the surface: the cell refuses the TCP below {MIN_TIP_MM:g} mm")
    if kind == "cube" and (far := [trial for trial, dx, _, _ in rows if abs(dx) > CUBE_MAX_DX_MM]):
        problems.append(
            f"{', '.join(far)}: more than {CUBE_MAX_DX_MM:g} mm along the jaws, where a finger may come down on the cube"
        )
    return problems


def placement_yaml(rows, part, bin_, task: str, kind: str = "screw", tip: float | None = None) -> str:
    where = "A screw's position is its head; its yaw points to its tip." if kind == "screw" else "A cube's position is its centre."
    lines = [
        "# Written by cell_policy/make_placement.py. Every rollout has the same objects in the same place; only the prompt",
        "# changes: its [c2f ...] tag is the grasp offset policy.py commands (the app's test-plan offset), so the operator",
        f"# places the {kind} and the bin the same way each time. {where}",
        "rollouts:",
    ]
    for i, (trial, dx, dy, dyaw) in enumerate(rows, 1):
        lines += [
            f"  - objects:                                     # rollout {i}",
            f"      {OBJECT_NAMES[kind]}: [{numbers(part, ', ')}]",
            f"      bin: [{numbers(bin_, ', ')}]",
            f'    prompt: "{task} {tag(trial, dx, dy, dyaw, part, bin_, kind, tip)}"',
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = p.add_mutually_exclusive_group()
    source.add_argument("--offsets", help='"dx,dy[,dyaw]; ..." in mm and degrees (default: a 10-rollout sweep across the jaws)')
    source.add_argument("--test-plan", type=Path, help="the app's test plan as JSON")
    p.add_argument("--design", help="--test-plan: only this design's rows (D1, STOCK, IMP, ...)")
    p.add_argument("--first", type=int, help="--test-plan: only the first N rows")
    p.add_argument("--trials", help="--test-plan: these trial IDs, in this order (T0001,T0002,...)")
    p.add_argument("--part", choices=sorted(TASKS), default="screw", help="the part to pick (default: screw)")
    p.add_argument("--screw", default=numbers(DEFAULT_SCREW), help="head x,y,yaw (mm, deg)")
    p.add_argument("--cube", default=numbers(DEFAULT_CUBE), help="centre x,y,yaw (mm, deg)")
    p.add_argument("--bin", default=numbers(DEFAULT_BIN), help="centre x,y[,yaw] (mm, deg)")
    p.add_argument("--tip", type=float, help="fingertips above the surface when they close, mm (default: policy.py's 2.5)")
    p.add_argument("--task", help="the instruction before the tag (default: the part's)")
    p.add_argument("--rollouts", type=int, help="fail unless there are exactly this many (submission.yaml's rollouts)")
    p.add_argument("-o", "--out", type=Path, help="write here instead of printing")
    args = p.parse_args(argv)

    kind = args.part
    part = tuple(float(v) for v in (args.cube if kind == "cube" else args.screw).split(","))
    bin_ = tuple(float(v) for v in args.bin.split(","))
    if len(part) != 3 or len(bin_) not in (2, 3):
        raise SystemExit(f"--{kind} is x,y,yaw and --bin is x,y[,yaw]")
    if args.test_plan:
        trials = [t.strip() for t in args.trials.split(",")] if args.trials else None
        rows = rows_from_plan(args.test_plan, args.design, args.first, trials)
    elif args.offsets:
        rows = rows_from_offsets(args.offsets)
    else:
        sweep = DEFAULT_CUBE_SWEEP if kind == "cube" else DEFAULT_SWEEP
        rows = [(f"R{i:02d}", float(dx), float(dy), float(dyaw)) for i, (dx, dy, dyaw) in enumerate(sweep, 1)]
    if not rows:
        raise SystemExit("no rollouts")
    if args.rollouts and len(rows) != args.rollouts:
        raise SystemExit(f"{len(rows)} rollouts, but submission.yaml asks for {args.rollouts}")
    if problems := check_layout(part, bin_, kind) + check_rollouts(rows, kind, args.tip):
        raise SystemExit("; ".join(problems))
    text = placement_yaml(rows, part, bin_, args.task or TASKS[kind], kind, args.tip)
    if args.out:
        args.out.write_text(text)
        print(f"wrote {len(rows)} rollouts to {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
