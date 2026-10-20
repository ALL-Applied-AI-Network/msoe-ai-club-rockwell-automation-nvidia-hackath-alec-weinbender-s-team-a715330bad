import pytest

from sim_server.models.gripper import GripperGeometry


def test_derived_dimensions():
    geo = GripperGeometry(
        carriage_x=0.217,
        finger_x=0.217,
        finger_length=0.076,
        finger_width=0.012,
        finger_thick=0.006,
        jaw_open=0.006,
        jaw_closed=0.0,
        finger_inner_tip=0.002,
        tip_clearance=0.0025,
        surface_dz=-0.0051,
        table_top_z=0.9,
    )
    assert geo.tip_offset == pytest.approx(0.293)
    assert geo.open_tip_gap == pytest.approx(0.016)
