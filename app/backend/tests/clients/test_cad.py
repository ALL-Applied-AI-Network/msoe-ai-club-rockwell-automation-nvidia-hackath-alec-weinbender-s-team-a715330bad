import pytest

from api.clients.cad import OpenScadCad
from api.models.design import SPACE, Design, clamp_params
from api.models.part import Part


@pytest.mark.parametrize("template", list(SPACE))
def test_export_is_an_openscad_body_for_every_template(template):
    design = Design(template=template, params=clamp_params(template, {}))

    scad = OpenScadCad().export(Part(), design)

    header, body = scad.rstrip().split("\n")
    assert header.startswith(f"// {template} finger")
    assert body.endswith((";", "}"))
    assert (body.count("{"), body.count("(")) == (body.count("}"), body.count(")"))
