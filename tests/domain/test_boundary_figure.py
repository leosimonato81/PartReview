# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Supports and loads get their own figure; result images carry result balloons only."""

from freecad.PartReview.domain import camera_planner as cp
from freecad.PartReview.domain.blocks import Figure
from freecad.PartReview.domain.colors import LOAD_RGB, SUPPORT_RGB
from freecad.PartReview.domain.hotspots import Hotspot, HotspotKind
from freecad.PartReview.domain.i18n import Translator
from freecad.PartReview.domain.models import FieldKind, Vec3
from freecad.PartReview.domain.report import build_report
from freecad.PartReview.domain.surface import build_surface, feature_edges, triangles_on

from test_i18n_report import make_inputs
from test_surface_hotspots import bar_mesh, square

ORIGIN = Vec3(0.0, 0.0, 0.0)


def boundary(kind, center, label):
    return Hotspot(kind=kind, center=center, radius=0.5, normal=None,
                   sample_points=(center,), color_field=FieldKind.VON_MISES, label=label,
                   anchors=(center,))


def figures(language="pt_BR"):
    report = build_report(make_inputs(), Translator(language, strict=True))
    return [b for b in report.blocks if isinstance(b, Figure)]


def test_supports_and_loads_figure_comes_first_with_category_legend():
    figs = figures()
    first = figs[0]
    assert first.view_index == 0 and first.caption.startswith("Figura 1 — Apoios e cargas")
    assert [rgb for rgb, _ in first.legend.swatches] == [SUPPORT_RGB, LOAD_RGB]
    assert first.markers == ()  # colors only, no balloons (owner's request)
    assert "Em roxo (apoios): Engaste." in first.balloons
    assert "Em laranja (cargas): Força (12,00 N)." in first.balloons
    assert "Seta" not in first.balloons  # colors only (owner's choice)
    # numbering follows the capture order: 1, 2, 3...
    assert [f.view_index for f in figs] == list(range(len(figs)))


def test_numbered_points_are_results_only():
    report = build_report(make_inputs(), Translator("pt_BR", strict=True))
    from freecad.PartReview.domain.blocks import Table
    points = [b for b in report.blocks if isinstance(b, Table) and b.header
              and b.header[0] == "Nº"][0]
    assert not any("Apoio" in row[1] or "Carga" in row[1] for row in points.rows)


def test_result_figures_have_only_result_balloons():
    for fig in figures()[1:]:
        assert fig.legend.swatches == ()
        assert all(m.style == "result" for m in fig.markers)
        assert "laranja" not in fig.balloons and "roxo" not in fig.balloons


def test_boundary_view_shows_every_support_and_load_when_visible():
    spots = [boundary(HotspotKind.SUPPORT, Vec3(-1, 0, 0), "A"),
             boundary(HotspotKind.LOAD, Vec3(1, 0, 0), "B"),
             Hotspot(kind=HotspotKind.STRESS_MAX, center=ORIGIN, radius=0.1, normal=None,
                     sample_points=(ORIGIN,), color_field=FieldKind.VON_MISES)]
    views = cp.plan_boundary_views(spots, ORIGIN, 2.0, lambda p, d: True)
    assert len(views) == 1 and views[0].color_field is None
    assert {t.label for t in views[0].targets} == {"A", "B"}  # results excluded


def test_a_second_view_only_for_hidden_supports_or_loads():
    front = boundary(HotspotKind.SUPPORT, Vec3(0, -1, 0), "front")
    back = boundary(HotspotKind.LOAD, Vec3(0, 1, 0), "back")

    def visible(p, d):  # a point is seen only by cameras looking toward it
        return (p.y < 0 and d.y > 0) or (p.y > 0 and d.y < 0)

    views = cp.plan_boundary_views([front, back], ORIGIN, 2.0, visible)
    assert len(views) == 2
    assert {t.label for v in views for t in v.targets} == {"front", "back"}
    assert len(cp.plan_boundary_views([front, back], ORIGIN, 2.0, visible, max_views=1)) == 1
    assert cp.plan_boundary_views([front, back], ORIGIN, 2.0, lambda p, d: False) == []


def test_feature_edges_are_the_box_outline():
    mesh, elements = bar_mesh(3)  # 3 x 1 x 1 bar of cubes
    surface = build_surface(elements, mesh.node_positions)
    edges = feature_edges(surface.triangles, mesh.node_positions)
    pos = mesh.node_positions
    for a, b in edges:  # every outline edge runs along a box edge (2 coordinates extreme)
        pa, pb = pos[a], pos[b]
        on = [k for k, hi in enumerate((3.0, 1.0, 1.0))
              if pa[k] in (0.0, hi) and pb[k] in (0.0, hi) and pa[k] == pb[k]]
        assert len(on) >= 2
    # the 4 long edges (3 segments each) + 2 end squares (4 edges each)
    assert len(edges) == 4 * 3 + 2 * 4


def test_triangles_on_finds_the_end_face_only():
    mesh, elements = bar_mesh(3)
    surface = build_surface(elements, mesh.node_positions)
    pos = mesh.node_positions
    found = triangles_on(square(0.0), surface.triangles, pos, 0.3 * surface.mean_edge_length)
    assert found
    for t in found:
        assert all(pos[n].x == 0.0 for n in surface.triangles[t])
    on_face = [t for t, tri in enumerate(surface.triangles) if all(pos[n].x == 0.0 for n in tri)]
    assert sorted(found) == on_face  # neighbors touching the edge are not taken


def test_supports_and_loads_figure_is_optional_and_never_in_the_quick_summary():
    from freecad.PartReview.domain.models import ReportConfig, ReportLevel
    c = ReportConfig()
    assert c.show_boundary is False  # beta: off unless the user ticks it
    c.show_boundary = True
    for level, wanted in ((ReportLevel.QUICK, False), (ReportLevel.STANDARD, True),
                          (ReportLevel.FULL, True)):
        c.level = level
        assert c.includes_boundary is wanted
    c.level, c.show_boundary = ReportLevel.FULL, False
    assert c.includes_boundary is False


def test_painting_follows_the_cad_edge_even_with_a_loose_tolerance():
    from freecad.PartReview.domain.surface import nearest_faces
    mesh, elements = bar_mesh(3)
    surface = build_surface(elements, mesh.node_positions)
    pos = mesh.node_positions
    def quad(a, b, c, d):
        return ((a, b, c), (a, c, d))

    v = [Vec3(x, y, z) for x in (0, 3) for y in (0, 1) for z in (0, 1)]  # box corners
    faces = {"P:Face1": square(0.0), "P:Face2": square(3.0),  # every face of the part
             "P:Face3": quad(v[0], v[4], v[6], v[2]), "P:Face4": quad(v[1], v[5], v[7], v[3]),
             "P:Face5": quad(v[0], v[4], v[5], v[1]), "P:Face6": quad(v[2], v[6], v[7], v[3])}
    # tolerance so loose that bottom triangles next to the end face are candidates too
    got = nearest_faces(surface.triangles, pos, faces, {"P:Face1"}, 0.9)
    end = {t for t, tri in enumerate(surface.triangles) if all(pos[n].x == 0.0 for n in tri)}
    assert set(got) == end and set(got.values()) == {"P:Face1"}
    assert nearest_faces(surface.triangles, pos, faces, {"P:Missing"}, 0.9) == {}
