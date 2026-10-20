"""A finger design: a point of one family's search space (typed parameters, see family.py), or one of the baselines that
every run includes."""

from typing import Literal

from pydantic import BaseModel, model_validator

from api.models.family import FamilyParams

DesignKind = Literal["search", "locked", "stock", "imprint"]


class Design(BaseModel):
    """What to build. 'search': a point the optimizer proposed. 'locked': a design the user fixed completely (a baseline
    of its own, "test my own design"). 'stock': the fingers already on the robot. 'imprint': a pocket shaped like the part,
    the usual hand-made design, which the judges' comparison needs. Search and locked designs carry their family's
    parameters; the two baselines are built from the part alone."""

    kind: DesignKind = "search"
    params: FamilyParams | None = None

    @model_validator(mode="after")
    def _params_match_kind(self) -> "Design":
        if self.kind in ("search", "locked") and self.params is None:
            raise ValueError(f"a {self.kind} design needs its family's parameters")
        if self.kind in ("stock", "imprint") and self.params is not None:
            raise ValueError(f"the {self.kind} baseline has no parameters")
        return self

    @property
    def family(self) -> str | None:
        return None if self.params is None else self.params.family
