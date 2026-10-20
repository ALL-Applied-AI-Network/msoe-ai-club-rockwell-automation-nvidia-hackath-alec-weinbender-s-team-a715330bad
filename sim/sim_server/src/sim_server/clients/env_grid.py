"""Where the environment copies sit, and which physics-view slot belongs to which copy. Isaac-free.

Copies are spread on a square grid far enough apart that nothing in one can touch another: the ER-4iA reaches about
0.55 m plus the 0.29 m tool from its base, and each copy's mat is 1.13 x 1.56 m, so 2 m spacing leaves clear gaps.

Isaac's batched views list their prims in an order we don't control (USD traversal for the view, pattern matching in the
physics tensor API). Rather than trust that, each slot is matched to a copy by where its body actually is.
"""

import math
from collections.abc import Sequence


def env_origins(n: int, spacing: float) -> list[tuple[float, float]]:
    """Row-major square grid in world XY, environment 0 at the origin."""
    cols = math.ceil(math.sqrt(n))
    return [((i % cols) * spacing, (i // cols) * spacing) for i in range(n)]


def slots_to_envs(slot_xy: Sequence[Sequence[float]], origins: Sequence[tuple[float, float]], max_distance: float) -> list[int]:
    """For each view slot, the environment whose origin is nearest its XY. Raises unless that is a one-to-one match
    with every slot within max_distance of its origin, which is what a correct scene gives."""
    if len(slot_xy) != len(origins):
        raise ValueError(f"the view has {len(slot_xy)} prims but there are {len(origins)} environments")
    envs = []
    for x, y in ((float(p[0]), float(p[1])) for p in slot_xy):
        distance, env = min((math.hypot(x - ox, y - oy), i) for i, (ox, oy) in enumerate(origins))
        if not distance <= max_distance:  # also catches NaN
            raise ValueError(f"a view prim at ({x:.3f}, {y:.3f}) is {distance:.3f} m from the nearest environment origin")
        envs.append(env)
    if len(set(envs)) != len(envs):
        raise ValueError("two view prims matched the same environment")
    return envs
