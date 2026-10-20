from pydantic import BaseModel, ConfigDict

Point = tuple[float, float, float]


class Piece(BaseModel):
    """One convex piece of a custom finger or a mesh part, in metres: its points and the hull's outward triangles.
    Physics uses the convex hull of the points; the triangles only make a valid mesh to author. A finger's pieces are in
    G (JawL's finger, jaws closed; see robot/gripper_frame.py), a part's in its own frame (see models/part.py)."""

    model_config = ConfigDict(frozen=True)

    points: tuple[Point, ...]
    triangles: tuple[tuple[int, int, int], ...]
