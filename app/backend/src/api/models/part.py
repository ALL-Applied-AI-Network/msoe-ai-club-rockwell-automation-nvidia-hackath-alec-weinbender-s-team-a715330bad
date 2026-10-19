from pydantic import BaseModel


class Part(BaseModel):
    """The object to grasp. Millimetres and grams; the twin works in metres, and sim_server converts."""

    shape: str = "sphere"
    diameter_mm: float = 40
    length_mm: float = 40
    mass_g: float = 50
