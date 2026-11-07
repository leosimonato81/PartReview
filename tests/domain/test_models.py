# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import pytest

from freecad.PartReview.domain.models import (
    Constraint,
    ConstraintKind,
    FemResult,
    FieldKind,
    Material,
    MeshInfo,
    ReportConfig,
    ResultField,
    UnitSystem,
    Vec3,
)
from freecad.PartReview.domain.units import Quantity


def make_mesh():
    positions = {
        1: Vec3(0.0, 0.0, 0.0),
        2: Vec3(10.0, 0.0, 0.0),
        3: Vec3(0.0, 20.0, 0.0),
        4: Vec3(0.0, 0.0, -5.0),
    }
    return MeshInfo(node_count=4, element_count=1, element_order=1,
                    length_unit="mm", node_positions=positions)


def make_stress():
    return ResultField(FieldKind.VON_MISES, "MPa",
                       node_ids=(1, 2, 3, 4), values=(0.1, 0.6, 0.3, 0.05))


def test_field_maximum_and_minimum_carry_position_and_unit():
    mesh = make_mesh()
    stress = make_stress()

    top = stress.maximum(mesh)
    assert top.node_id == 2
    assert top.position == Vec3(10.0, 0.0, 0.0)
    assert top.value == Quantity(0.6, "MPa")

    low = stress.minimum(mesh)
    assert low.node_id == 4
    assert low.value.unit == "MPa"


def test_field_rejects_mismatched_lengths_and_empty():
    with pytest.raises(ValueError):
        ResultField(FieldKind.VON_MISES, "MPa", node_ids=(1, 2), values=(0.1,))
    with pytest.raises(ValueError):
        ResultField(FieldKind.VON_MISES, "MPa", node_ids=(), values=())


def test_mesh_bounding_box():
    low, high = make_mesh().bounding_box()
    assert low == Vec3(0.0, 0.0, -5.0)
    assert high == Vec3(10.0, 20.0, 0.0)


def test_mesh_validates_order_and_node_count():
    with pytest.raises(ValueError):
        MeshInfo(4, 1, 3, "mm", make_mesh().node_positions)
    with pytest.raises(ValueError):
        MeshInfo(5, 1, 1, "mm", make_mesh().node_positions)


def test_fem_result_get_field():
    result = FemResult(
        label="CCX_Results", solver="CalculiX", analysis_type="static",
        mesh=make_mesh(), fields={FieldKind.VON_MISES: make_stress()},
        materials=(Material("PLA", yield_strength=Quantity(50.0, "MPa")),),
        constraints=(Constraint(ConstraintKind.FORCE, "ConstraintForce",
                                ("Shroud 001:Face6",), Quantity(12.0, "N"),
                                Vec3(0.0, 0.0, -1.0)),),
    )
    assert result.get_field(FieldKind.VON_MISES) is not None
    assert result.get_field(FieldKind.DISPLACEMENT) is None


def test_report_config_valid():
    config = ReportConfig(result_name="CCX_Results", language="en",
                          title="Suporte", output_path="/tmp/r.PDF")
    assert config.validate() == []


def test_report_config_defaults_to_mpa_mm_units():
    assert ReportConfig().unit_system is UnitSystem.MPA_MM
    bad = ReportConfig(result_name="x", output_path="r.pdf", unit_system="kPa")
    assert bad.validate() == ["config.error.unit_system"]


def test_report_config_reports_i18n_keys():
    config = ReportConfig(language="fr", output_path="report.txt")
    assert config.validate() == [
        "config.error.no_result",
        "config.error.language",
        "config.error.output_not_pdf",
    ]
    assert "config.error.no_output" in ReportConfig(result_name="x").validate()
