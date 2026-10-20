"""Environment layout and matching physics-view slots to environments by position."""

import pytest

from sim_server.clients.env_grid import env_origins, slots_to_envs


def test_origins_form_a_square_grid():
    assert env_origins(1, 2.0) == [(0.0, 0.0)]
    assert env_origins(5, 2.0) == [(0.0, 0.0), (2.0, 0.0), (4.0, 0.0), (0.0, 2.0), (2.0, 2.0)]
    assert len(set(env_origins(64, 2.0))) == 64


def test_slots_match_whatever_order_the_view_uses():
    origins = env_origins(4, 2.0)
    shuffled = [(2.0 + 0.3, 2.0 - 0.01), (0.31, 0.0), (0.0, 2.0), (2.0, 0.0)]  # e.g. parts near (0.30, 0) of each env
    assert slots_to_envs([(x - 0.3, y) for x, y in shuffled], origins, 1.0) == [3, 0, 2, 1]


def test_slot_matching_refuses_a_wrong_scene():
    origins = env_origins(3, 2.0)
    with pytest.raises(ValueError, match="same environment"):
        slots_to_envs([(0, 0), (0.1, 0), (2, 0)], origins, 1.0)
    with pytest.raises(ValueError, match="from the nearest"):
        slots_to_envs([(0, 0), (2, 0), (9, 9)], origins, 1.0)
    with pytest.raises(ValueError, match="from the nearest"):
        slots_to_envs([(0, 0), (2, 0), (float("nan"), 0)], origins, 1.0)
    with pytest.raises(ValueError, match="3 environments"):
        slots_to_envs([(0, 0)], origins, 1.0)
