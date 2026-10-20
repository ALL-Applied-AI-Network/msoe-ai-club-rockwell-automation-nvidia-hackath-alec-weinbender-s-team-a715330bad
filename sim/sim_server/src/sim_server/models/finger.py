from pydantic import BaseModel, ConfigDict

from sim_server.models.piece import Piece


class FingerDesign(BaseModel):
    """The fingers one row of a batch is tried with. pieces None means the twin's own (stock) fingers. tip_height and
    jaw_close are metres; for stock fingers they're optional overrides of the twin's cube rule (services/batches.py)."""

    model_config = ConfigDict(frozen=True)

    id: str
    pieces: tuple[Piece, ...] | None = None
    friction: tuple[float, float] | None = None  # (static, dynamic), custom fingers only
    tip_height: float | None = None
    jaw_close: float | None = None

    @property
    def is_stock(self) -> bool:
        return self.pieces is None

    @property
    def finger_key(self) -> tuple | None:
        """What the authored fingers depend on. Two designs with the same key need no stage edit between them."""
        return None if self.is_stock else (self.pieces, self.friction)
