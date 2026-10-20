"""The offset grid under an error model, for input step 7's picture: every offset with its weight, the error's 1σ and 2σ
circles, the outer ring, the yaw layers and warnings. Pure computation (no database, no sim), cheap enough to call on
every slider move: the weights take a few milliseconds and are cached.
"""

from api.models.error_model import ErrorModel
from api.models.offset_grid import GridPreview, OffsetGrid
from api.models.part import Part


def grid_preview(part: Part, error: ErrorModel, final: bool = False) -> GridPreview:
    """The search grid a job on this part would use (final=True: the dense grid of the final test), under this error."""
    grid = OffsetGrid.for_part(part, error)
    return (grid.refined() if final else grid).preview(error)
