# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import datetime
import re

import pytest

from freecad.PartReview.domain import camera_planner as cp
from freecad.PartReview.domain.hotspots import (
    constraint_hotspot,
    field_hotspots,
    mark_singularities,
)
from freecad.PartReview.domain.i18n import Translator, load_messages
from freecad.PartReview.domain.models import (
    Constraint,
    ConstraintKind,
    FemResult,
    FieldKind,
    Material,
    ReportConfig,
    ResultField,
    Vec3,
)
from freecad.PartReview.domain.report import (
    Figure,
    Notice,
    ReportInputs,
    Table,
    build_report,
    order_hotspots,
    safety_factor,
)
from freecad.PartReview.domain.surface import build_surface
from freecad.PartReview.domain.units import Quantity

from test_surface_hotspots import bar_mesh, square, stress_on_bar


def test_locales_have_the_same_keys_and_placeholders():
    pt, en = load_messages("pt_BR"), load_messages("en")
    assert set(pt) == set(en)
    for key in pt:
        assert set(re.findall(r"{(\w+)}", pt[key])) == set(re.findall(r"{(\w+)}", en[key])), key


def test_translator_formats_numbers_by_language():
    pt, en = Translator("pt_BR"), Translator("en")
    assert pt.quantity(Quantity(0.6137, "MPa")) == "0,614 MPa"
    assert en.quantity(Quantity(0.6137, "MPa")) == "0.614 MPa"
    assert pt.point(Vec3(1.5, -2.25, 0.0), "mm") == "(1,50; -2,25; 0) mm"
    assert pt.date(datetime.date(2026, 11, 6)) == "06/11/2026"
    assert en.t("missing.key") == "missing.key"
    with pytest.raises(KeyError):
        Translator("en", strict=True).t("missing.key")
    with pytest.raises(ValueError):
        Translator("fr")


def test_safety_factor():
    assert safety_factor(Quantity(250.0, "MPa"), Quantity(100.0, "MPa")) == 2.5
    with pytest.raises(ValueError):
        safety_factor(Quantity(250.0, "MPa"), Quantity(100.0, "kPa"))


def make_inputs(yield_strength=None):
    mesh, elements = bar_mesh(6)
    surface = build_surface(elements, mesh.node_positions)
    stress = stress_on_bar(mesh)
    ids = tuple(mesh.node_positions)
    disp = ResultField(FieldKind.DISPLACEMENT, "mm", ids,
                       tuple(mesh.node_positions[n].x * 0.01 for n in ids))
    fixed = Constraint(ConstraintKind.FIXED, "Engaste", ("Peça:Face1",), geometry=square(0.0))
    load = Constraint(ConstraintKind.FORCE, "Força", ("Peça:Face2",), Quantity(12.0, "N"),
                      Vec3(0, 0, -1), geometry=square(6.0))
    result = FemResult("CCX_Results", "CalculiX", "static", mesh,
                       {FieldKind.VON_MISES: stress, FieldKind.DISPLACEMENT: disp},
                       (Material("Aço", Quantity(210000.0, "MPa"), 0.3,
                                 Quantity(7900.0, "kg/m^3")),),
                       (fixed, load))
    spots = field_hotspots(stress, mesh, surface) + field_hotspots(disp, mesh, surface)
    spots += [constraint_hotspot(fixed), constraint_hotspot(load)]
    spots = order_hotspots(mark_singularities(spots, [fixed, load], 0.5))
    center, radius = Vec3(3, 0.5, 0.5), 3.5

    def visible(p, d):
        return True

    results = [s for s in spots if s.kind not in cp.BOUNDARY_KINDS]  # as report_job
    views = [cp.plan_overview(FieldKind.VON_MISES, results, center, radius, visible)]
    views += [cp.plan_target_view(s, center, radius, visible) for s in results]
    views = cp.select_views(views)
    boundary = cp.plan_boundary_views(spots, center, radius, visible)
    config = ReportConfig(result_name="CCX_Results", title="Suporte do motor",
                          author="Leo", output_path="r.pdf")
    return ReportInputs(result=result, config=config, hotspots=spots, views=views,
                        image_size=(1600, 1200), document_name="a.FCStd",
                        date=datetime.date(2026, 11, 6), yield_strength=yield_strength,
                        yield_source="user" if yield_strength else "", max_on_surface=True,
                        tool_version="0.1.0", freecad_version="1.1.4",
                        boundary_views=boundary)


@pytest.mark.parametrize("language", ["pt_BR", "en"])
def test_report_builds_with_every_text_translated(language):
    report = build_report(make_inputs(Quantity(5.0, "MPa")), Translator(language, strict=True))
    assert report.title == "Suporte do motor"  # user text untouched
    figures = [b for b in report.blocks if isinstance(b, Figure)]
    assert 2 <= len(figures) <= 8
    assert figures[0].caption.startswith("Fig")
    for fig in figures:
        if fig.legend.swatches:  # supports and loads figure: category legend
            continue
        assert fig.legend.ticks[0][0] == 0.0 and fig.legend.ticks[-1][0] == 1.0
        for m in fig.markers:
            assert 0 <= m.u <= 1600 and 0 <= m.v <= 1200
    notices = [b for b in report.blocks if isinstance(b, Notice)]
    # safety factor 5/10 = 0.5 < 1, and both stress peaks sit on constraints
    assert len([n for n in notices if n.level == "warning"]) >= 3


def test_report_tables_contain_values_and_user_labels():
    report = build_report(make_inputs(), Translator("pt_BR", strict=True))
    text = "\n".join(cell for b in report.blocks if isinstance(b, Table)
                     for row in b.rows for cell in row)
    assert "10,00 MPa" in text  # max von Mises, 4 significant digits
    assert "Engaste" in text and "Força: 12,00 N" in text
    assert "Aço" in text
    notices = [b.text for b in report.blocks if isinstance(b, Notice)]
    assert any("escoamento não informado" in n for n in notices)


def test_report_shows_images_before_tables():
    """Executive summary opens the report; after it, images come before tables."""
    from freecad.PartReview.domain.report import Heading
    blocks = list(build_report(make_inputs(), Translator("pt_BR", strict=True)).blocks)
    assert isinstance(blocks[0], Heading) and blocks[0].text == "1. Resumo executivo"
    views = next(i for i, b in enumerate(blocks) if isinstance(b, Heading) and b.anchor == "fem.views")
    rest = blocks[views:]
    first_figure = next(i for i, b in enumerate(rest) if isinstance(b, Figure))
    first_table = next(i for i, b in enumerate(rest) if isinstance(b, Table))
    assert first_figure < first_table


def test_section_order_views_first():
    from freecad.PartReview.domain.report import Heading
    blocks = build_report(make_inputs(), Translator("pt_BR", strict=True)).blocks
    titles = [b.text for b in blocks if isinstance(b, Heading)]
    assert titles == ["1. Resumo executivo", "2. Vistas", "3. Resumo da análise",
                      "4. Resultados principais", "5. Pontos de interesse",
                      "6. Premissas e limitações"]


def test_section_numbers_have_no_gap_without_points():
    from freecad.PartReview.domain.report import Heading
    inputs = make_inputs()
    inputs.hotspots = []
    inputs.boundary_views = []
    inputs.views = [v for v in inputs.views if v.is_overview]
    inputs.views = [type(v)(v.camera, v.color_field, (), True) for v in inputs.views]
    titles = [b.text for b in build_report(inputs, Translator("en", strict=True)).blocks
              if isinstance(b, Heading)]
    assert titles == ["1. Executive summary", "2. Views", "3. Analysis summary",
                      "4. Main results", "5. Assumptions and limitations"]


def test_balloons_are_explained_under_each_figure_and_in_the_table():
    report = build_report(make_inputs(), Translator("pt_BR", strict=True))
    figures = [b for b in report.blocks if isinstance(b, Figure)]
    shown = {}
    for fig in figures:
        numbers = [m.number for m in fig.markers]
        assert numbers == sorted(numbers)
        listed = [int(x) for x in re.findall(r"(\d+) = ", fig.balloons)]
        assert listed == numbers  # every balloon drawn is explained, nothing else
        for n in numbers:
            shown.setdefault(str(n), []).append(str(fig.view_index + 1))
    points = [b for b in report.blocks if isinstance(b, Table) and b.header
              and b.header[0] == "Nº"][0]
    for row in points.rows:
        assert row[4] == ("; ".join(shown[row[0]]) if row[0] in shown else "—")


def _points_table(report):
    return [b for b in report.blocks if isinstance(b, Table) and b.header
            and b.header[0] == "Nº"][0]


def test_alert_column_only_when_a_point_has_an_alert():
    from dataclasses import replace
    inputs = make_inputs()  # both stress peaks sit on constraints in this model
    table = _points_table(build_report(inputs, Translator("pt_BR", strict=True)))
    assert table.header[-1] == "Alerta"
    assert any(row[-1].startswith("possível singularidade") for row in table.rows)

    inputs.hotspots = [replace(h, singularity_near="") for h in inputs.hotspots]
    inputs.views = [replace(v, targets=tuple(replace(t, singularity_near="")
                                             for t in v.targets)) for v in inputs.views]
    table = _points_table(build_report(inputs, Translator("pt_BR", strict=True)))
    assert "Alerta" not in table.header and "Observação" not in table.header
    assert all(len(row) == len(table.header) == 5 for row in table.rows)
