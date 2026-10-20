"""Training data as JSON Lines, one object per line, for the stretch-goal models."""

import json

from fastapi import APIRouter, Response

from api.dependencies import DbDep
from api.services import export

router = APIRouter(prefix="/api/export", tags=["export"])


def _jsonl(rows: list[dict]) -> Response:
    return Response("\n".join(json.dumps(row) for row in rows), media_type="application/x-ndjson")


@router.get("/physical.jsonl")
def export_physical(db: DbDep) -> Response:
    return _jsonl(export.physical_rows(db))


@router.get("/trials.jsonl")
def export_trials(db: DbDep) -> Response:
    return _jsonl(export.trial_rows(db))
