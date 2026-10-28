"""Read a benchmark checkpoint without modifying or resuming the experiment."""

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    checkpoint = args.run / "results.json"
    if not checkpoint.is_file():
        parser.error(f"no checkpoint yet: {checkpoint}")
    state = json.loads(checkpoint.read_text(encoding="utf-8"))
    rows = state["observations"]
    searched = [row for row in rows if row["phase"] == "search" and row["method"] in ("bo", "sobol", "ga")]
    exit_file = Path(f"{args.run}.exit-code")
    result = {
        "status": state["status"],
        "badge": state["badge"],
        "config": state["config"],
        "finished_exit_code": int(exit_file.read_text().strip()) if exit_file.is_file() else None,
        "candidate_evaluations_completed": len(searched),
        "candidate_evaluations_planned": state.get("estimate", {}).get("candidate_evaluations"),
        "saved_observations": len(rows),
        "submitted_grasps": sum(row["grasps"] for row in rows),
        "returned_measurements": sum(row.get("measured_grasps") or 0 for row in rows),
        "last_checkpoint_runtime_s": state.get("wall_s"),
        "last_completed": {key: rows[-1][key] for key in ("seed", "method", "phase", "batch")} if rows else None,
        "selection_summaries": [
            {key: search.get(key) for key in ("seed", "method", "selection", "wall_s")} for search in state["searches"]
        ],
        "error": state.get("error"),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
