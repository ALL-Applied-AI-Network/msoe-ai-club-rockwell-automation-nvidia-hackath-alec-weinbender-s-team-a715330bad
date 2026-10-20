"""Simulated results as JSON Lines, one object per line, for analysis and the stretch-goal surrogate models."""

import json

from fastapi import APIRouter, HTTPException, Response

from api.dependencies import DbDep
from api.services import export, jobs

router = APIRouter(prefix="/api/export", tags=["export"])


def jsonl(rows: list[dict], filename: str | None = None) -> Response:
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'} if filename else None
    return Response("".join(json.dumps(row) + "\n" for row in rows), media_type="application/x-ndjson", headers=headers)


@router.get("/trials.jsonl")
def trials_jsonl(db: DbDep, job_id: str | None = None) -> Response:
    """Every trial (one design on the search or final grid) with its raw outcomes: one job's, or every job's."""
    try:
        rows = export.trial_rows(db, job_id)
    except jobs.JobNotFoundError:
        raise HTTPException(404, f"no job {job_id}") from None
    return jsonl(rows, f"trials_{job_id}.jsonl" if job_id else "trials.jsonl")
