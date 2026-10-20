"""input flow and outputs: parts, cell profiles, experiments, raw outcomes, test plans

The input-flow and outputs overhaul (docs/notes/input-flow-backend-plan.md): uploaded parts, versioned cell profiles,
experiments (name, EXP id, spec, plan), trials with raw outcomes (in-hand pose, held after transport) on the search and
final grids, results with STEP/STL files and export checks, printed fingers, test plans, and physical trials logged
against them. Old job rows don't fit and are demo data, so, as 0002 did, the upgrade drops the job tables and builds
them again empty. The downgrade restores the 0002 schema, empty.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TABLES = ("jobs", "trials", "results", "run_meta", "reviews", "physical_trials")
NEW_TABLES = (
    "cell_profiles",
    "jobs",
    "parts",
    "physical_trials",
    "printed_fingers",
    "results",
    "reviews",
    "run_meta",
    "test_plans",
    "trials",
)


def upgrade() -> None:
    for table in OLD_TABLES:
        op.drop_table(table)
    op.create_table(
        "cell_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created", sa.Double(), nullable=False),
        sa.Column("profile", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("experiment_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created", sa.Double(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "finalizing", "done", "failed", "cancelled", "interrupted", native_enum=False),
            nullable=False,
        ),
        sa.Column("part_id", sa.String(), nullable=False),
        sa.Column("cell_profile_id", sa.Integer(), nullable=False),
        sa.Column("sim_backend", sa.String(), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column("part", sa.JSON(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("n_done", sa.Integer(), nullable=False),
        sa.Column("n_total", sa.Integer(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("n_rounds", sa.Integer(), nullable=False),
        sa.Column("best_value", sa.Double(), nullable=True),
        sa.Column("best_trial", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("failure", sa.String(), nullable=True),
        sa.Column("failed_step", sa.Integer(), nullable=True),
        sa.Column("cancel_requested", sa.Integer(), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("finished", sa.Double(), nullable=True),
        sa.Column("duplicated_from", sa.String(), nullable=True),
        sa.Column("print_designs", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("experiment_number"),
    )
    op.create_table(
        "parts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created", sa.Double(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("units", sa.String(), nullable=False),
        sa.Column("measured", sa.JSON(), nullable=False),
        sa.Column("material", sa.String(), nullable=True),
        sa.Column("density_g_cm3", sa.Double(), nullable=True),
        sa.Column("surface", sa.String(), nullable=False),
        sa.Column("mass_g", sa.Double(), nullable=True),
        sa.Column("mass_unit", sa.String(), nullable=False),
        sa.Column("fragile", sa.Boolean(), nullable=False),
        sa.Column("max_grip_force_n", sa.Double(), nullable=True),
        sa.Column("clearance_mm", sa.Double(), nullable=True),
        sa.Column("pose", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "physical_trials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=True),
        sa.Column("trial_id", sa.String(), nullable=False),
        sa.Column("design_label", sa.String(), nullable=False),
        sa.Column("finger_id", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("offset_x_mm", sa.Double(), nullable=False),
        sa.Column("offset_y_mm", sa.Double(), nullable=False),
        sa.Column("yaw_deg", sa.Double(), nullable=False),
        sa.Column("repeat", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("in_tolerance", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.String(), nullable=False),
        sa.Column("video_link", sa.String(), nullable=True),
        sa.Column("operator", sa.String(), nullable=True),
        sa.Column("timestamp", sa.String(), nullable=True),
        sa.Column("history", sa.JSON(), nullable=False),
        sa.Column("created", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "trial_id"),
    )
    op.create_table(
        "printed_fingers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("finger_id", sa.String(), nullable=False),
        sa.Column("design_label", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("material", sa.String(), nullable=False),
        sa.Column("print_date", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=False),
        sa.Column("created", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "results",
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("trial_number", sa.Integer(), nullable=False),
        sa.Column("search", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("grasp_pose", sa.JSON(), nullable=False),
        sa.Column("predicted_success", sa.Double(), nullable=False),
        sa.Column("capture_radius_mm", sa.Double(), nullable=True),
        sa.Column("cad_files", sa.JSON(), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("created", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_table(
        "reviews",
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("status", sa.Enum("approved", "rejected", "pending", native_enum=False), nullable=False),
        sa.Column("reviewer", sa.String(), nullable=False),
        sa.Column("notes", sa.String(), nullable=False),
        sa.Column("created", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_table(
        "run_meta",
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_table(
        "test_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("created", sa.Double(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("designs", sa.JSON(), nullable=False),
        sa.Column("rows", sa.JSON(), nullable=False),
        sa.Column("prediction_status", sa.String(), nullable=False),
        sa.Column("prediction_error", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "trials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("search", sa.String(), nullable=False),
        sa.Column("grid", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("success_rate", sa.Double(), nullable=False),
        sa.Column("capture_radius_mm", sa.Double(), nullable=True),
        sa.Column("n_grasps", sa.Integer(), nullable=False),
        sa.Column("n_success", sa.Integer(), nullable=False),
        sa.Column("held", sa.JSON(), nullable=False),
        sa.Column("in_hand", sa.JSON(), nullable=False),
        sa.Column("held_after_transport", sa.JSON(), nullable=True),
        sa.Column("duration", sa.Double(), nullable=False),
        sa.Column("created", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "number"),
    )


def downgrade() -> None:
    for table in NEW_TABLES:
        op.drop_table(table)
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created", sa.Double(), nullable=False),
        sa.Column("status", sa.String(length=11), nullable=False),
        sa.Column("part_name", sa.String(), nullable=False),
        sa.Column("part_path", sa.String(), nullable=True),
        sa.Column("part", sa.JSON(), nullable=False),
        sa.Column("task", sa.String(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("n_done", sa.Integer(), nullable=False),
        sa.Column("n_total", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(), nullable=True),
        sa.Column("best_value", sa.Double(), nullable=True),
        sa.Column("best_trial", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("cancel_requested", sa.Integer(), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("finished", sa.Double(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "physical_trials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("created", sa.Double(), nullable=False),
        sa.Column("finger", sa.String(), nullable=False),
        sa.Column("success", sa.Integer(), nullable=False),
        sa.Column("placement_error_mm", sa.Double(), nullable=True),
        sa.Column("cycle_time_s", sa.Double(), nullable=True),
        sa.Column("recovered", sa.Integer(), nullable=False),
        sa.Column("operator_intervention", sa.Integer(), nullable=False),
        sa.Column("notes", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "results",
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("trial_number", sa.Integer(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("grasp_pose", sa.JSON(), nullable=False),
        sa.Column("predicted_success", sa.Double(), nullable=False),
        sa.Column("scad_path", sa.String(), nullable=False),
        sa.Column("created", sa.Double(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("capture_radius_mm", sa.Double(), nullable=True),
        sa.Column("comparison", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_table(
        "reviews",
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("reviewer", sa.String(), nullable=False),
        sa.Column("notes", sa.String(), nullable=False),
        sa.Column("created", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_table(
        "run_meta",
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_table(
        "trials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("success_rate", sa.Double(), nullable=False),
        sa.Column("n_grasps", sa.Integer(), nullable=False),
        sa.Column("n_success", sa.Integer(), nullable=False),
        sa.Column("duration", sa.Double(), nullable=False),
        sa.Column("created", sa.Double(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("capture_radius_mm", sa.Double(), nullable=True),
        sa.Column("held", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "number"),
    )
