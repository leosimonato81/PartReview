# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Steel, aluminium, PLA, ABS, PETG: the right criterion and limit for each."""

from dataclasses import replace

import pytest

from freecad.PartReview.domain.blocks import BulletList, Table
from freecad.PartReview.domain.i18n import Translator
from freecad.PartReview.domain.models import (FieldKind, Material, ResultField,
                                              material_family)
from freecad.PartReview.domain.report import build_report
from freecad.PartReview.domain.units import Quantity

from test_i18n_report import make_inputs


@pytest.mark.parametrize("e_mpa, family", [(210000, "metal"), (70000, "metal"),
                                           (3640, "polymer"), (2300, "polymer"),
                                           (2100, "polymer"), (12000, "other"), (None, "other")])
def test_family_from_youngs_modulus(e_mpa, family):
    assert material_family(e_mpa) == family  # steel, aluminium, PLA, ABS, PETG, wood


def pla_inputs():
    inputs = make_inputs()
    pla = Material("PLA", Quantity(3640.0, "MPa"), 0.36, None, Quantity(35.9, "MPa"),
                   Quantity(26.4, "MPa"), family="polymer")
    mesh = inputs.result.mesh
    ids = tuple(mesh.node_positions)
    principal = ResultField(FieldKind.PRINCIPAL_MAX, "MPa", ids,
                            tuple(8.0 if mesh.node_positions[n].x == 0 else 1.0 for n in ids))
    fields = dict(inputs.result.fields)
    fields[FieldKind.PRINCIPAL_MAX] = principal
    inputs.result = replace(inputs.result, materials=(pla,), fields=fields)
    inputs.yield_strength, inputs.yield_source = Quantity(26.4, "MPa"), "material_uts"
    return inputs


def text(report):
    parts = []
    for b in report.blocks:
        if isinstance(b, Table):
            parts += [c for row in b.rows for c in row]
        elif isinstance(b, BulletList):
            parts += list(b.items)
    return "\n".join(parts)


def test_polymer_gets_rankine_and_the_lower_limit():
    t = text(build_report(pla_inputs(), Translator("pt_BR", strict=True)))
    assert "Limite usado: resistência à tração" in t
    assert "critério de Rankine" in t and "3,30" in t  # 26,4 / 8 = 3,3
    assert "impressa em 3D" in t and "fluência" in t


def test_metal_keeps_von_mises_only():
    t = text(build_report(make_inputs(Quantity(250.0, "MPa")), Translator("pt_BR", strict=True)))
    assert "Rankine" not in t and "impressa em 3D" not in t


def test_support_reactions_table():
    from freecad.PartReview.domain.models import Vec3
    inputs = make_inputs()
    inputs.reactions = [("Engaste", Vec3(0.0, 0.0, 12.0))]
    report = build_report(inputs, Translator("pt_BR", strict=True))
    table = next(b for b in report.blocks if isinstance(b, Table) and b.header
                 and b.header[0] == "Apoio")
    assert table.rows[0][0] == "Engaste" and table.rows[0][3] == "12,0 N"
    assert table.rows[0][4] == "12,0 N"


def test_volume_above_fractions_of_the_limit():
    from freecad.PartReview.domain.models import Vec3
    from freecad.PartReview.domain.quality import volume_above
    pos = {1: Vec3(0, 0, 0), 2: Vec3(1, 0, 0), 3: Vec3(0, 1, 0), 4: Vec3(0, 0, 1),
           5: Vec3(1, 1, 1)}
    # two tetrahedra of volume 1/6 and 1/3; the small one is highly stressed
    elements = [(1, 2, 3, 4), (2, 3, 4, 5)]
    stress = {1: 100.0, 2: 100.0, 3: 100.0, 4: 100.0, 5: -260.0}
    shares = dict(volume_above(elements, pos, stress, 100.0))
    # element 1 mean 100 (>= all fractions), element 2 mean (300-260)/4 = 10 (none)
    v1, v2 = 1 / 6, 1 / 3
    assert shares[1.0] == pytest.approx(v1 / (v1 + v2))
    assert shares[0.5] == shares[1.0]


def test_volume_table_appears_with_a_yield_strength():
    from test_surface_hotspots import bar_mesh
    inputs = make_inputs(Quantity(12.0, "MPa"))
    inputs.result = replace(inputs.result, elements=tuple(bar_mesh(6)[1]))
    report = build_report(inputs, Translator("pt_BR", strict=True))
    table = next(b for b in report.blocks if isinstance(b, Table) and b.header
                 and b.header[0] == "Tensão de von Mises")
    assert [r[0] for r in table.rows][0].startswith("≥ 50 % do limite")
