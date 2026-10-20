"""Send a grasp batch to the sim server and print what was held, without the app. Standard library only, so any Python
3.11+ runs it (the uv venv, Isaac's python.sh, or a bare python3 on the GPU machine).

    python sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/stock_cube.json
    python sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/stock_cube.json --grid --out runs/s1_grid.json
    python sim/sim_server/scripts/send_batch.py sim/sim_server/scripts/batches/heavy_block_grip_force.json --grip-force none
    python sim/sim_server/scripts/send_batch.py --compare runs/s1_grid.json runs/s2_grid.json

--url is the server's base URL (default http://127.0.0.1:9000; through `brev port-forward` it's the forwarded local port).
--grid replaces the file's offsets with the app's default offset grid (app/backend/src/api/models/offset_grid.py): the
centre plus rings at 1, 2, 3, 4, 5, 6, 7, 8, 10 and 12 mm, 8 directions each, at yaw 0: 81 points (more with --yaws).
--grip-force and --transport override the file's grip_force_n and transport ("none" sends null), for sweeps.
--out saves the request, response and timing as JSON; --compare reads two such files and reports where they disagree:
held and held after transport exactly, the in-hand pose as differences where both runs held the part.
"""

import argparse
import json
import logging
import math
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger("send_batch")

GRID_RADII_MM = (1, 2, 3, 4, 5, 6, 7, 8, 10, 12)
GRID_DIRECTIONS = 8
IN_HAND_FIELDS = ("dx", "dy", "dz", "tilt", "yaw")  # mm, mm, mm, deg, deg
TRANSPORTS = ("slow", "normal", "fast")


def grid_offsets(radii=GRID_RADII_MM, n_directions=GRID_DIRECTIONS, yaws=(0.0,)) -> list[dict]:
    """Same points and order as the app's OffsetGrid.points(): for each yaw, the centre, then each ring going round
    (direction 0 is +dx, toward JawL; then counter-clockwise toward +dy)."""
    ring = [(math.cos(2 * math.pi * j / n_directions), math.sin(2 * math.pi * j / n_directions)) for j in range(n_directions)]
    return [
        {"dx": round(r * c, 9), "dy": round(r * s, 9), "yaw_deg": yaw}
        for yaw in yaws
        for r, c, s in [(0.0, 1.0, 0.0), *((r, c, s) for r in radii for c, s in ring)]
    ]


def post(url: str, batch: dict, timeout_s: float) -> dict:
    request = urllib.request.Request(url.rstrip("/") + "/evaluate_batch", json.dumps(batch).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} from {url}: {e.read().decode(errors='replace')}") from e


def apply_overrides(batch: dict, grip_force: str | None, transport: str | None) -> dict:
    """The batch with --grip-force / --transport applied ("none" -> null); arguments left out keep the file's values."""
    batch = dict(batch)
    if grip_force is not None:
        batch["grip_force_n"] = None if grip_force.lower() == "none" else float(grip_force)
    if transport is not None:
        batch["transport"] = None if transport.lower() == "none" else transport
    return batch


def grid_map(held: list[bool], n_yaws: int) -> list[str]:
    """Rings as rows, directions as columns: '#' held, '.' dropped."""
    per_yaw = 1 + len(GRID_RADII_MM) * GRID_DIRECTIONS
    lines = []
    for y in range(n_yaws):
        block = held[y * per_yaw : (y + 1) * per_yaw]
        lines.append(f"  centre        {'#' if block[0] else '.'}")
        for k, r in enumerate(GRID_RADII_MM):
            row = block[1 + k * GRID_DIRECTIONS : 1 + (k + 1) * GRID_DIRECTIONS]
            lines.append(f"  r = {r:>4} mm   {''.join('#' if ok else '.' for ok in row)}")
    return lines


def in_hand_text(pose: list[float] | None) -> str:
    if pose is None:
        return ""
    dx, dy, dz, tilt, yaw = pose
    return f"in hand dx {dx:6.2f} dy {dy:6.2f} dz {dz:6.2f} mm, tilt {tilt:5.1f}, yaw {yaw:6.1f} deg"


def in_hand_summary(poses: list[list[float] | None]) -> str:
    """Offset = the 3-D distance from the centred position (the backend's measure), plus the largest tilt and yaw."""
    held = [p for p in poses if p is not None]
    if not held:
        return "no in-hand poses"
    offsets = [math.dist(p[:3], (0, 0, 0)) for p in held]
    return (
        f"in hand over {len(held)} held: offset median {statistics.median(offsets):.2f} mm, max {max(offsets):.2f} mm; "
        f"max |tilt| {max(abs(p[3]) for p in held):.1f} deg, max |yaw| {max(abs(p[4]) for p in held):.1f} deg"
    )


def report(batch: dict, response: dict, grid_yaws: int | None) -> None:
    held, after = response["held"], response.get("held_after_transport")
    in_hand = response.get("in_hand") or [[None] * len(row) for row in held]
    for d, (design, row) in enumerate(zip(batch["designs"], held, strict=True)):
        logger.info("%-16s held %d/%d%s", design["id"], sum(row), len(row), "" if after is None else f", after transport {sum(after[d])}")
        if grid_yaws:
            logger.info("\n".join(grid_map(row, grid_yaws)))
            if after is not None:
                logger.info("  after transport:\n%s", "\n".join(grid_map(after[d], grid_yaws)))
            logger.info("  %s", in_hand_summary(in_hand[d]))
            continue
        for o, (offset, ok) in enumerate(zip(batch["offsets"], row, strict=True)):
            kept = "" if after is None else ("  kept in transport" if after[d][o] else "  lost in transport" if ok else "")
            logger.info(
                "  dx %6.2f  dy %6.2f  yaw %6.1f   %-7s %s%s",
                offset["dx"],
                offset["dy"],
                offset["yaw_deg"],
                "held" if ok else "dropped",
                in_hand_text(in_hand[d][o]),
                kept,
            )
    if response.get("sim"):
        logger.info("Sim: %s", json.dumps(response["sim"]))


def in_hand_differences(rows_a: list | None, rows_b: list | None) -> list[list[float]]:
    """Per field, |a - b| at every offset where both runs report an in-hand pose (yaw wrapped to the short way round)."""
    diffs: list[list[float]] = [[] for _ in IN_HAND_FIELDS]
    for row_a, row_b in zip(rows_a or [], rows_b or [], strict=False):
        for a, b in zip(row_a, row_b, strict=True):
            if a is None or b is None:
                continue
            for i, (x, y) in enumerate(zip(a, b, strict=True)):
                diffs[i].append(abs((x - y + 180) % 360 - 180) if IN_HAND_FIELDS[i] == "yaw" else abs(x - y))
    return diffs


def compare(a_path: Path, b_path: Path) -> int:
    """Exit 0 when held (and held after transport, where both have it) agree everywhere. In-hand differences are
    reported, not judged: they're continuous, and how close is close enough is for the experiment log."""
    a, b = (json.loads(p.read_text()) for p in (a_path, b_path))
    if a["request"]["offsets"] != b["request"]["offsets"] or [d["id"] for d in a["request"]["designs"]] != [
        d["id"] for d in b["request"]["designs"]
    ]:
        raise SystemExit("the two runs don't have the same designs and offsets")
    after_a, after_b = a["response"].get("held_after_transport"), b["response"].get("held_after_transport")
    total = same = 0
    for d, (design, row_a, row_b) in enumerate(zip(a["request"]["designs"], a["response"]["held"], b["response"]["held"], strict=True)):
        diff = [i for i, (x, y) in enumerate(zip(row_a, row_b, strict=True)) if x != y]
        if after_a is not None and after_b is not None:
            diff += [i for i, (x, y) in enumerate(zip(after_a[d], after_b[d], strict=True)) if x != y and i not in diff]
        total, same = total + len(row_a), same + len(row_a) - len(diff)
        logger.info("%-16s agree %d/%d; held %d vs %d", design["id"], len(row_a) - len(diff), len(row_a), sum(row_a), sum(row_b))
        for i in sorted(diff):
            o = a["request"]["offsets"][i]
            transported = "" if after_a is None or after_b is None else f"; after transport {after_a[d][i]} vs {after_b[d][i]}"
            logger.info(
                "  offset %d (dx %.2f, dy %.2f, yaw %.1f): %s vs %s%s", i, o["dx"], o["dy"], o["yaw_deg"], row_a[i], row_b[i], transported
            )
    diffs = in_hand_differences(a["response"].get("in_hand"), b["response"].get("in_hand"))
    if diffs[0]:
        logger.info(
            "In-hand differences over %d grasps both held (median / max): %s",
            len(diffs[0]),
            ", ".join(f"{name} {statistics.median(v):.2f} / {max(v):.2f}" for name, v in zip(IN_HAND_FIELDS, diffs, strict=True)),
        )
    logger.info(
        "Overall agreement %d/%d (%.1f%%); %s took %.1f s, %s took %.1f s",
        same,
        total,
        100 * same / max(total, 1),
        a_path.name,
        a["elapsed_s"],
        b_path.name,
        b["elapsed_s"],
    )
    return 0 if same == total else 1


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("batch", nargs="?", type=Path, help="JSON request body for POST /evaluate_batch")
    parser.add_argument("--url", default="http://127.0.0.1:9000", help="sim server base URL")
    parser.add_argument("--grid", action="store_true", help="use the app's 81-point offset grid instead of the file's offsets")
    parser.add_argument("--yaws", default="0", help="comma-separated yaws (deg) for --grid, e.g. 0,-10,10")
    parser.add_argument("--grip-force", help="per-jaw force limit in newtons, or 'none' for the twin's drive (overrides the file)")
    parser.add_argument("--transport", choices=(*TRANSPORTS, "none"), help="transport move after the lift (overrides the file)")
    parser.add_argument("--timeout", type=float, default=3600, help="seconds to wait for the response")
    parser.add_argument("--out", type=Path, help="save request, response and timing here")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("A", "B"), help="compare two --out files instead of sending")
    args = parser.parse_args()
    if args.compare:
        return compare(*args.compare)
    if args.batch is None:
        parser.error("give a batch file, or --compare A B")
    batch = apply_overrides(json.loads(args.batch.read_text()), args.grip_force, args.transport)
    yaws = [float(v) for v in args.yaws.split(",")]
    if args.grid:
        batch["offsets"] = grid_offsets(yaws=yaws)
    n_grasps = len(batch["designs"]) * len(batch["offsets"])
    logger.info(
        "Sending %d design(s) x %d offset(s) = %d grasps to %s (grip force %s, transport %s)",
        len(batch["designs"]),
        len(batch["offsets"]),
        n_grasps,
        args.url,
        batch.get("grip_force_n"),
        batch.get("transport"),
    )
    started = time.perf_counter()
    response = post(args.url, batch, args.timeout)
    elapsed = time.perf_counter() - started
    logger.info("Answered in %.1f s (%.2f grasps/s, including queueing)", elapsed, n_grasps / elapsed if elapsed else 0.0)
    report(batch, response, len(yaws) if args.grid else None)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"url": args.url, "elapsed_s": elapsed, "request": batch, "response": response}) + "\n")
        logger.info("Saved %s", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
