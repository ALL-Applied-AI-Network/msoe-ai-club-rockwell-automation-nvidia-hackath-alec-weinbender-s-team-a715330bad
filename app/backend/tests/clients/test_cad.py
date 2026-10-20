from api.clients.cad import OpenScadCad
from api.models.design import Design
from api.models.finger import build_finger
from api.models.part import Part


def test_export_is_openscad_of_every_simulated_piece_for_both_fingers():
    finger = build_finger(Part(), Design(kind="imprint"))

    scad = OpenScadCad().export(finger, "imprint for the cap")

    assert scad.startswith("// imprint for the cap\n")
    assert scad.count("polyhedron(") == len(finger.pieces)
    assert scad.count("finger();") == 2
    assert (scad.count("{"), scad.count("("), scad.count("[")) == (scad.count("}"), scad.count(")"), scad.count("]"))
