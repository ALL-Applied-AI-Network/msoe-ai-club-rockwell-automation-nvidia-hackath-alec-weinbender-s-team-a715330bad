import cadquery as cq
import numpy as np
import pytest

from api.models.resting_pose import AS_AUTHORED, IDENTITY, RestingPose, resting_poses, table_transform, to_table_frame


@pytest.fixture(scope="module")
def poses(cad, shapes, tmp_path_factory):
    """poses(name) -> (PartMesh, the part's resting poses, its centre of mass), each test part read once."""
    cache = {}

    def of(name):
        if name not in cache:
            path = tmp_path_factory.mktemp("parts") / f"{name}.step"
            cq.exporters.export(shapes[name], str(path))
            measured, mesh = cad.read_part(path.name, path.read_bytes())
            cache[name] = mesh, resting_poses(mesh, measured.centre_of_mass_mm), measured.centre_of_mass_mm
        return cache[name]

    return of


def labels(poses):
    return [pose.label for pose in poses]


def test_a_cubes_six_faces_are_one_pose(poses):
    _, found, _ = poses("cube")

    assert labels(found) == ["standing", AS_AUTHORED]
    assert found[0].probability == pytest.approx(1.0)
    assert found[0].extent_mm == pytest.approx((10, 10, 10))


def test_a_cylinders_side_facets_merge_into_lying_on_its_side(poses):
    _, found, _ = poses("glass_tube")

    assert labels(found) == ["lying on its side", "standing on an end", AS_AUTHORED]
    lying, standing, authored = found
    assert lying.probability > 0.9 and lying.probability + standing.probability == pytest.approx(1.0, abs=1e-3)
    assert lying.extent_mm == pytest.approx((140, 17, 17), abs=0.05)  # longer side of the footprint along x
    assert standing.extent_mm == pytest.approx((17, 17, 140), abs=0.05)
    assert (authored.source, authored.probability, authored.rotation) == ("as_authored", None, IDENTITY)


def test_the_cup_stands_on_an_end_or_lies_on_its_side(poses):
    _, found, _ = poses("vial_cap")

    assert labels(found) == ["standing on an end", "lying on its side", AS_AUTHORED]
    assert found[1].extent_mm == pytest.approx((31.75, 15.7, 31.75), abs=0.05)


def test_a_plate_lies_flat_or_stands_on_its_edge(poses):
    _, found, _ = poses("wide_plate")

    assert labels(found) == ["lying flat", "on its side", AS_AUTHORED]
    assert found[1].extent_mm == pytest.approx((120, 4, 120))


def test_the_l_bracket_keeps_the_four_likeliest_poses_then_as_authored(poses):
    _, found, _ = poses("l_bracket")

    assert len(found) == 5 and found[-1].source == "as_authored"
    likelihoods = [pose.probability for pose in found[:-1]]
    assert likelihoods == sorted(likelihoods, reverse=True)
    assert found[0].label == "lying flat" and "standing" in labels(found)


def test_poses_are_proper_rotations_and_the_same_every_time(poses):
    mesh, found, com = poses("l_bracket")

    again = resting_poses(mesh, com)

    for pose in found:
        r = np.array(pose.rotation)
        assert r @ r.T == pytest.approx(np.eye(3), abs=1e-9) and np.linalg.det(r) == pytest.approx(1)
    assert again == found  # so a stored pose index keeps meaning the same pose


def test_count_limits_the_stable_poses(poses):
    mesh, found, com = poses("l_bracket")

    assert resting_poses(mesh, com, count=1) == [found[0], found[-1]]


def test_the_table_frame_rests_on_z_0_with_the_footprint_centred(poses):
    mesh, found, _ = poses("glass_tube")
    standing = next(p for p in found if p.label == "standing on an end")

    points = to_table_frame(mesh.vertices, standing)

    lo, hi = points.min(axis=0), points.max(axis=0)
    assert lo[2] == pytest.approx(0) and (lo[:2] + hi[:2]) == pytest.approx((0, 0), abs=1e-9)
    assert hi - lo == pytest.approx(standing.extent_mm, abs=1e-3)


def test_one_transform_moves_other_points_with_the_part(poses):
    mesh, found, _ = poses("l_bracket")
    rotation, shift = table_transform(mesh.vertices, found[1])

    corner = mesh.vertices[0]

    assert to_table_frame(mesh.vertices, found[1])[0] == pytest.approx(rotation @ corner + shift)


def test_as_authored_is_the_cad_frame(poses):
    mesh, _, _ = poses("cube")

    assert to_table_frame(mesh.vertices, None) == pytest.approx(mesh.vertices)
    assert to_table_frame(
        mesh.vertices, RestingPose(rotation=IDENTITY, label=AS_AUTHORED, source="as_authored", extent_mm=(10, 10, 10))
    ) == (pytest.approx(mesh.vertices))
