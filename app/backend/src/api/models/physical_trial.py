from pydantic import BaseModel, ConfigDict


class PhysicalTrial(BaseModel):
    """One grasp attempt on the real arm, logged by hand after a supervised test."""

    model_config = ConfigDict(from_attributes=True)  # read straight from api.db.tables rows

    id: int
    job_id: str
    created: float
    finger: str  # "optimized", "stock", "imprint", ...
    success: int
    placement_error_mm: float | None
    cycle_time_s: float | None
    recovered: int
    operator_intervention: int
    notes: str
