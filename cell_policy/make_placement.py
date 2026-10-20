"""Write submission/placement.yaml for a test-plan run on the real cell: the same screw and bin pose every rollout, and
each rollout's prompt tagged with the grasp offset policy.py should command (see policy.py's docstring).

    python make_placement.py --offsets "0,0,0; 3,0,0; -3,0,0" -o submission/placement.yaml
    python make_placement.py --test-plan plan.json --design D1 --first 10 -o submission/placement.yaml

--test-plan reads the app's test plan as JSON (GET /api/jobs/{job_id}/test-plans/{plan_id}, or a list of its rows): each
row's trial_id, offset_x_mm, offset_y_mm and yaw_deg. Standard library only, so it runs under any Python 3.10+.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

TASK = "Put the screw into the yellow bin."
DEFAULT_SCREW = (420.0, -40.0, 90.0)  # head x, y (mm, robot frame) and yaw (deg, head to tip): keep policy.py's in step
DEFAULT_BIN = (480.0, 120.0, 0.0)
# Ten offsets across the jaws (dx, mm), where the fingers' design matters most: the shank is 6 mm in a 12 mm opening.
DEFAULT_SWEEP = [(0, 0, 0), (1.5, 0, 0), (-1.5, 0, 0), (3, 0, 0), (-3, 0, 0), (4.5, 0, 0), (-4.5, 0, 0), (6, 0, 0), (-6, 0, 0), (0, 0, 0)]
REACH_MM = 540.0
X_RANGE_MM = (150.0, 650.0)
MIN_SCREW_TO_BIN_MM = 50.0


def numbers(values, sep: str = ",") -> str:
    return sep.join(f"{v:g}" for v in values)


def tag(trial: str, dx: float, dy: float, dyaw: float, screw, bin_) -> str:
    """The prompt tag policy.py parses."""
    return f"[c2f trial={trial} dx={dx:+.2f} dy={dy:+.2f} dyaw={dyaw:+.1f} screw={numbers(screw)} bin={numbers(bin_)}]"


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


def check_layout(screw, bin_) -> list[str]:
    problems = []
    for name, (x, y, *_) in (("screw", screw), ("bin", bin_)):
        if math.hypot(x, y) > REACH_MM:
            problems.append(f"the {name} is {math.hypot(x, y):.0f} mm from the base axis, past {REACH_MM:g} mm")
        if not X_RANGE_MM[0] <= x <= X_RANGE_MM[1]:
            problems.append(f"the {name}'s x {x:g} mm is outside {X_RANGE_MM[0]:g}..{X_RANGE_MM[1]:g} mm")
    if math.hypot(screw[0] - bin_[0], screw[1] - bin_[1]) < MIN_SCREW_TO_BIN_MM:
        problems.append("the screw is too close to the bin")
    return problems


def placement_yaml(rows, screw, bin_, task: str) -> str:
    lines = [
        "# Written by cell_policy/make_placement.py. Every rollout has the same objects in the same place; only the prompt",
        "# changes: its [c2f ...] tag is the grasp offset policy.py commands (the app's test-plan offset), so the operator",
        "# places the screw and the bin the same way each time. A screw's position is its head; its yaw points to its tip.",
        "rollouts:",
    ]
    for i, (trial, dx, dy, dyaw) in enumerate(rows, 1):
        lines += [
            f"  - objects:                                     # rollout {i}",
            f"      screw: [{numbers(screw, ', ')}]",
            f"      bin: [{numbers(bin_, ', ')}]",
            f'    prompt: "{task} {tag(trial, dx, dy, dyaw, screw, bin_)}"',
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
    p.add_argument("--screw", default=numbers(DEFAULT_SCREW), help="head x,y,yaw (mm, deg)")
    p.add_argument("--bin", default=numbers(DEFAULT_BIN), help="centre x,y[,yaw] (mm, deg)")
    p.add_argument("--task", default=TASK)
    p.add_argument("--rollouts", type=int, help="fail unless there are exactly this many (submission.yaml's rollouts)")
    p.add_argument("-o", "--out", type=Path, help="write here instead of printing")
    args = p.parse_args(argv)

    screw = tuple(float(v) for v in args.screw.split(","))
    bin_ = tuple(float(v) for v in args.bin.split(","))
    if len(screw) != 3 or len(bin_) not in (2, 3):
        raise SystemExit("--screw is x,y,yaw and --bin is x,y[,yaw]")
    if args.test_plan:
        trials = [t.strip() for t in args.trials.split(",")] if args.trials else None
        rows = rows_from_plan(args.test_plan, args.design, args.first, trials)
    elif args.offsets:
        rows = rows_from_offsets(args.offsets)
    else:
        rows = [(f"R{i:02d}", float(dx), float(dy), float(dyaw)) for i, (dx, dy, dyaw) in enumerate(DEFAULT_SWEEP, 1)]
    if not rows:
        raise SystemExit("no rollouts")
    if args.rollouts and len(rows) != args.rollouts:
        raise SystemExit(f"{len(rows)} rollouts, but submission.yaml asks for {args.rollouts}")
    if problems := check_layout(screw, bin_):
        raise SystemExit("; ".join(problems))
    text = placement_yaml(rows, screw, bin_, args.task)
    if args.out:
        args.out.write_text(text)
        print(f"wrote {len(rows)} rollouts to {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
