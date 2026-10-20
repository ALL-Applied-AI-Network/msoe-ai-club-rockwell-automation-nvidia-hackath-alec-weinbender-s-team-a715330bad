import time

import pytest

from api.models.error_model import ErrorModel
from api.models.part import Part
from api.services.grids import grid_preview


def test_an_upright_cylinder_gets_one_layer_and_a_box_three():
    assert grid_preview(Part(), ErrorModel()).n_offsets == 81
    box = grid_preview(Part(shape="box"), ErrorModel(sigma_deg=6))
    assert (box.n_offsets, box.yaws_deg) == (243, [-9, 0, 9])


def test_the_final_grid_is_the_dense_one():
    preview = grid_preview(Part(shape="box"), ErrorModel(), final=True)

    assert preview.n_offsets == 963 and preview.outer_ring_mm == 12 and preview.covered_to_mm == 12.5


def test_the_preview_carries_the_error_and_its_warnings():
    preview = grid_preview(Part(), ErrorModel(sigma_mm=4, bias_mm=5, bias_direction_deg=180))

    assert preview.circles[1].radius_mm == 8 and preview.circles[1].centre_mm == pytest.approx((-5, 0))
    assert preview.warnings == ["bias + 2σ (13.0 mm) reaches past the 12 mm outer ring: errors beyond the grid count as misses"]
    assert preview.coverage < 0.97, "about 4% of the error lands beyond the grid"


def test_it_is_fast_enough_for_a_slider():
    """Each slider move is a new error model, so nothing is cached: the dense grid with a bias, yaw and a range of sigmas
    is the slowest case."""
    started = time.perf_counter()
    for i in range(5):
        grid_preview(Part(shape="box"), ErrorModel(sigma_range_mm=(1 + i / 10, 4), bias_mm=1.5, bias_direction_deg=30), final=True)

    assert (time.perf_counter() - started) / 5 < 0.25
