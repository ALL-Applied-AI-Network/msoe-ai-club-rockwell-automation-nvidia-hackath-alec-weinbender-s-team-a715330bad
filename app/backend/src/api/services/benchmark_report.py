"""Portable, dependency-free benchmark artifacts, including incomplete runs."""

import csv
import html
import json
import statistics
from pathlib import Path


def checkpoint(output: Path, state: dict) -> None:
    temporary = output / "results.tmp"
    temporary.write_text(json.dumps(state, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(output / "results.json")


def report(output: Path, state: dict) -> None:
    rows = state["observations"]
    grid_kind = "PILOT" if state["config"].get("pilot") else "STANDARD"
    title = f"{state['badge'].upper()} {grid_kind} benchmark - {state['status']}"
    columns = [
        "seed",
        "method",
        "phase",
        "number",
        "batch",
        "success_rate",
        "capture_radius_mm",
        "grasps",
        "measured_grasps",
        "cumulative_grasps",
        "proposal_s",
        "geometry_s",
        "simulator_s",
        "source",
        "fallback_reason",
        "duplicate_parameters",
        "duplicate_geometry",
        "rejections",
        "parameter_hash",
        "geometry_hash",
    ]
    with (output / "candidates.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["badge", "status", "grid_kind", "design_json", *columns])
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "badge": state["badge"],
                    "status": state["status"],
                    "grid_kind": grid_kind,
                    "design_json": json.dumps(row["design"], sort_keys=True),
                    **{column: row.get(column) for column in columns},
                }
            )
    lines = [
        f"# {title}",
        "",
        "MOCK is geometry only, not physics evidence. Isaac results still require hardware review.",
        "Error distribution and throughput are assumptions. CPU reference settings and server revision require operator verification.",
        "Incomplete runs cannot support a comparison conclusion.",
        "PILOT uses only center and +/-4 mm at yaw zero: its scores are diagnostic, not full-grid accuracy estimates."
        if grid_kind == "PILOT"
        else "Standard search and dense validation grids.",
        "",
        f"Total elapsed: {state.get('wall_s', 0):.2f} s",
        f"Submitted simulator grasps (all phases): {sum(row['grasps'] for row in rows)}",
        "The server may skip stock grasps that do not fit. Returned landing measurements are counted separately; "
        "missing measurements do not establish how many physics attempts ran.",
        f"Returned physics measurements: {sum(row.get('measured_grasps') or 0 for row in rows)} "
        f"across {sum(row.get('measured_grasps') is not None for row in rows)} measured rows.",
        "",
        "| Seed | Method | Selection mean | Holdout mean | Holdout SD | Search/final seconds | Patience prefix |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for search in state["searches"]:
        selection_score = search.get("selection", {}).get("mean", search["winner"]["success_rate"])
        repeats = [
            row["success_rate"]
            for row in rows
            if row["seed"] == search["seed"] and row["method"] == search["method"] and row["phase"] == "repeat"
        ]
        mean = f"{statistics.mean(repeats):.6f}" if repeats else "pending"
        deviation = f"{statistics.stdev(repeats):.6f}" if len(repeats) > 1 else "pending"
        lines.append(
            f"| {search['seed']} | {search['method']} | {selection_score:.6f} | {mean} | {deviation} | "
            f"{search['wall_s']:.2f} | {search['patience_would_stop_at']} |"
        )
    lines += [
        "",
        "## Paired holdout-score differences (method minus Sobol)",
        "",
        "Only fresh winner repeats enter this comparison; the selection score is excluded.",
    ]
    for method in ("bo", "ga"):
        differences = []
        for seed in state["config"]["seeds"]:
            scores = {}
            for candidate in ("bo", "sobol", "ga"):
                held_out = [
                    row["success_rate"] for row in rows if row["seed"] == seed and row["method"] == candidate and row["phase"] == "repeat"
                ]
                if len(held_out) == 3:
                    scores[candidate] = statistics.mean(held_out)
            if method in scores and "sobol" in scores:
                difference = scores[method] - scores["sobol"]
                differences.append(difference)
                lines.append(f"- Seed {seed}, {method}: {difference:+.6f}")
        if differences:
            deviation = f"{statistics.stdev(differences):.6f}" if len(differences) > 1 else "not estimable"
            lines.append(f"- {method} paired mean {statistics.mean(differences):+.6f}; across-seed SD {deviation} (n={len(differences)}).")
    lines += ["", "## Baselines (selection and independent holdout)", ""]
    baselines = [row for row in rows if row["method"] == "baseline" and row["phase"] == "final"]
    for seed, kind in sorted({(row["seed"], row["design"]["kind"]) for row in baselines}):
        selected = [row["success_rate"] for row in baselines if row["seed"] == seed and row["design"]["kind"] == kind]
        repeats = [row["success_rate"] for row in rows if row["seed"] == seed and row["method"] == kind and row["phase"] == "repeat"]
        lines.append(f"- Seed {seed} {kind}: selection mean {statistics.mean(selected):.6f} (n={len(selected)}); holdout {repeats}")
    lines += ["", "## Diagnostics", ""]
    for phase in ("search", "final", "repeat"):
        selected = [row for row in rows if row["phase"] == phase]
        lines.append(
            f"- {phase}: {sum(row['grasps'] for row in selected)} simulator grasps; "
            f"{sum(row['simulator_s'] for row in selected):.2f} simulator seconds (all methods and baselines)."
        )
    for method in ("bo", "sobol", "ga"):
        scores = [
            search.get("selection", {}).get("mean", search["winner"]["success_rate"])
            for search in state["searches"]
            if search["method"] == method
        ]
        if scores:
            deviation = f"{statistics.stdev(scores):.6f}" if len(scores) > 1 else "not estimable"
            lines.append(f"- {method} selection score mean {statistics.mean(scores):.6f}; across-seed SD {deviation} (n={len(scores)}).")
        selected = [row for row in rows if row["method"] == method and row["phase"] == "search"]
        lines.append(
            f"- {method}: {len(selected)} candidates; {sum(row['grasps'] for row in selected)} grasps; "
            f"{sum(bool(row['rejections']) for row in selected)} rejected; "
            f"{sum(row['duplicate_parameters'] for row in selected)} duplicate parameters; "
            f"{sum(row['duplicate_geometry'] for row in selected)} duplicate geometries; "
            f"{len({(row['seed'], row['batch']) for row in selected if row['source'] == 'sobol_fallback'})} fallback batches."
        )
        lines.append(
            "  Time (seconds): "
            + ", ".join(f"{key}={sum(row[key] for row in selected):.2f}" for key in ("proposal_s", "geometry_s", "simulator_s"))
        )
    if state.get("error"):
        lines += ["", "## Failure", "", state["error"]]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for axis in ("candidates", "grasps"):
        _plot(output / f"convergence-{axis}.svg", rows, title, axis)


def _plot(path: Path, rows: list[dict], title: str, axis: str) -> None:
    search = [row for row in rows if row["phase"] == "search" and row["method"] != "baseline"]
    groups = sorted({(row["seed"], row["method"]) for row in search})
    maximum = max((row["number"] + 1 if axis == "candidates" else row["cumulative_grasps"] for row in search), default=1) or 1
    label = "submitted grasps" if axis == "grasps" else "candidate evaluations"
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="480" viewBox="0 0 900 480">',
        '<rect width="900" height="480" fill="white"/>',
        f'<text x="30" y="25" font-size="18">{html.escape(title)}</text>',
        '<text x="30" y="48">Best search score (0 to 1); each line is one seed; MOCK is not physics</text>',
        '<path d="M60 70 V410 H860" fill="none" stroke="black"/>',
        f'<text x="60" y="450">0 to {maximum} {label}; BO blue, Sobol orange, GA green</text>',
    ]
    for level in range(6):
        vertical = 410 - level * 68
        svg.append(f'<text x="15" y="{vertical}">{level / 5:.1f}</text>')
    colors = {"bo": "#1261a0", "sobol": "#c66b10", "ga": "#288440"}
    for seed, method in groups:
        best, points = 0.0, []
        for row in search:
            if (row["seed"], row["method"]) != (seed, method):
                continue
            best = max(best, row["success_rate"])
            horizontal = row["number"] + 1 if axis == "candidates" else row["cumulative_grasps"]
            points.append(f"{60 + 800 * horizontal / maximum:.2f},{410 - 340 * best:.2f}")
        svg.append(
            f'<polyline points="{" ".join(points)}" fill="none" stroke="{colors[method]}" opacity="0.7">'
            f"<title>{method} seed {seed}</title></polyline>"
        )
    path.write_text("\n".join([*svg, "</svg>"]), encoding="utf-8")
