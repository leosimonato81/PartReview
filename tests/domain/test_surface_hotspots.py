# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import pytest

from freecad.PartReview.domain import geometry as g
from freecad.PartReview.domain.hotspots import (
    HotspotKind,
    constraint_hotspot,
    field_hotspots,
    find_clusters,
    gradient_hotspot,
    mark_singularities,
)
from freecad.PartReview.domain.models import (
    Constraint,
    ConstraintKind,
    FieldKind,
    MeshInfo,
    ResultField,
    Vec3,
)
from freecad.PartReview.domain.surface import build_surface


def bar_mesh(n=6):
    """A bar of ``n`` cubes along X, each split in 6 tetrahedra (Kuhn split)."""
    positions = {}
    ids = {}
    for i in range(n + 1):
        for j in (0, 1):
            for k in (0, 1):
                nid = len(positions) + 1
                ids[(i, j, k)] = nid
                positions[nid] = Vec3(float(i), float(j), float(k))
    elements = []
    for i in range(n):
        c = [ids[(i + dx, dy, dz)] for dx in (0, 1) for dy in (0, 1) for dz in (0, 1)]
        # cube corners: index = dx*4 + dy*2 + dz ; six tets around diagonal 0-7
        for a, b in ((1, 3), (3, 2), (2, 6), (6, 4), (4, 5), (5, 1)):
            elements.append((c[0], c[a], c[b], c[7]))
    mesh = MeshInfo(len(positions), len(elements), 1, "mm", positions)
    return mesh, elements


def test_single_tet_surface_outward_normals():
    pos = {1: Vec3(0, 0, 0), 2: Vec3(1, 0, 0), 3: Vec3(0, 1, 0), 4: Vec3(0, 0, 1)}
    s = build_surface([(1, 2, 3, 4)], pos)
    assert len(s.triangles) == 4
    center = g.centroid(pos.values())
    for a, b, c in s.triangles:
        n = g.cross(g.sub(pos[b], pos[a]), g.sub(pos[c], pos[a]))
        assert g.dot(n, g.sub(g.centroid([pos[a], pos[b], pos[c]]), center)) > 0
    # node 1 sits at the origin corner: its normal points away from the solid
    assert g.dot(s.normals[1], Vec3(-1, -1, -1)) > 0


def test_bar_surface_excludes_shared_faces():
    mesh, elements = bar_mesh(3)
    s = build_surface(elements, mesh.node_positions)
    # 3 cubes: outer area = 2*(3*1)*2 + 2 ends = 14 unit squares = 28 triangles
    assert len(s.triangles) == 28
    assert s.nodes == frozenset(mesh.node_positions)


def test_quadratic_tet_mid_nodes_join_the_graph():
    pos = {1: Vec3(0, 0, 0), 2: Vec3(2, 0, 0), 3: Vec3(0, 2, 0), 4: Vec3(0, 0, 2)}
    mids = {5: (1, 2), 6: (2, 3), 7: (3, 1), 8: (1, 4), 9: (2, 4), 10: (3, 4)}
    for m, (a, b) in mids.items():
        pos[m] = g.scale(g.add(pos[a], pos[b]), 0.5)
    s = build_surface([tuple(range(1, 11))], pos)
    assert s.nodes == frozenset(range(1, 11))
    assert set(s.neighbors[5]) == {1, 2}
    with pytest.raises(ValueError):
        build_surface([(1, 2, 3, 4, 5)], pos)


def test_find_clusters_splits_disconnected_groups():
    neighbors = {1: (2,), 2: (1, 3), 3: (2, 4), 4: (3, 5), 5: (4,)}
    clusters = find_clusters({1, 2, 4, 5}, neighbors)
    assert sorted(sorted(c) for c in clusters) == [[1, 2], [4, 5]]


def stress_on_bar(mesh, hot_x=(0.0, 6.0)):
    """Stress peaks at both ends of the bar, bigger at x=6."""
    ids = tuple(mesh.node_positions)
    values = []
    for nid in ids:
        x = mesh.node_positions[nid].x
        values.append(max(0.0, 10.0 - 4 * abs(x - 6.0)) + max(0.0, 7.0 - 4 * abs(x - 0.0)))
    return ResultField(FieldKind.VON_MISES, "MPa", ids, tuple(values))


def test_field_hotspots_find_both_ends_in_order():
    mesh, elements = bar_mesh(6)
    surface = build_surface(elements, mesh.node_positions)
    spots = field_hotspots(stress_on_bar(mesh), mesh, surface, threshold_ratio=0.6)
    assert [s.kind for s in spots] == [HotspotKind.STRESS_MAX, HotspotKind.STRESS]
    assert spots[0].center.x == 6.0 and spots[0].peak_value.value == 10.0
    assert spots[1].center.x == 0.0
    assert spots[0].peak_value.unit == "MPa"
    assert spots[0].normal is not None


def test_displacement_gives_single_max_hotspot():
    mesh, elements = bar_mesh(4)
    surface = build_surface(elements, mesh.node_positions)
    ids = tuple(mesh.node_positions)
    disp = ResultField(FieldKind.DISPLACEMENT, "mm", ids,
                       tuple(mesh.node_positions[n].x for n in ids))
    spots = field_hotspots(disp, mesh, surface)
    assert [s.kind for s in spots] == [HotspotKind.DISPLACEMENT_MAX]
    assert spots[0].center.x == 4.0


def test_gradient_hotspot_found_where_values_jump():
    mesh, elements = bar_mesh(6)
    surface = build_surface(elements, mesh.node_positions)
    ids = tuple(mesh.node_positions)
    step = ResultField(FieldKind.VON_MISES, "MPa", ids,
                       tuple(10.0 if mesh.node_positions[n].x >= 3 else 0.0 for n in ids))
    spot = gradient_hotspot(step, mesh, surface, top_fraction=0.3)
    assert spot is not None and spot.kind is HotspotKind.GRADIENT
    assert spot.center.x in (2.0, 3.0)
    assert spot.peak_value.unit == "MPa/mm"


def square(x0):
    a, b, c, d = Vec3(x0, 0, 0), Vec3(x0, 1, 0), Vec3(x0, 1, 1), Vec3(x0, 0, 1)
    return ((a, b, c), (a, c, d))


def test_constraint_hotspot_and_singularity():
    fixed = Constraint(ConstraintKind.FIXED, "Fixo", geometry=square(0.0))
    load = Constraint(ConstraintKind.FORCE, "Força", geometry=square(6.0))
    spot = constraint_hotspot(fixed)
    assert spot.kind is HotspotKind.SUPPORT and spot.label == "Fixo"
    assert spot.center.x == 0.0  # on the face (x = 0), near its middle
    assert abs(spot.center.y - 0.5) < 0.25 and abs(spot.center.z - 0.5) < 0.25
    assert spot.anchors == (spot.center,)
    assert constraint_hotspot(load).kind is HotspotKind.LOAD
    assert constraint_hotspot(Constraint(ConstraintKind.FIXED, "x")) is None

    mesh, elements = bar_mesh(6)
    surface = build_surface(elements, mesh.node_positions)
    spots = field_hotspots(stress_on_bar(mesh), mesh, surface)
    marked = mark_singularities(spots, [fixed, load], tolerance=0.5)
    assert marked[0].singularity_near == "Força"  # peak at x=6 sits on the load face
    assert marked[1].singularity_near == "Fixo"


def test_stress_on_an_edge_support_is_flagged_as_singular():
    from freecad.PartReview.domain.geometry import point_segment_distance
    from freecad.PartReview.domain.hotspots import distance_to_constraint
    from freecad.PartReview.domain.models import Constraint, ConstraintKind, Vec3
    assert point_segment_distance(Vec3(1, 1, 0), Vec3(0, 0, 0), Vec3(2, 0, 0)) == 1.0
    assert point_segment_distance(Vec3(5, 0, 0), Vec3(0, 0, 0), Vec3(2, 0, 0)) == 3.0
    edge = Constraint(ConstraintKind.FIXED, "ConstraintFixed", ("Shroud 001:Edge23",),
                      lines=((Vec3(21, 6.9, 14), Vec3(21, 8, 14)),))
    assert edge.on_edges_or_vertices
    assert distance_to_constraint(Vec3(21.0, 6.9, 14.0), edge) == 0.0  # owner's max stress
    face = Constraint(ConstraintKind.FIXED, "F", ("P:Face2",))
    assert not face.on_edges_or_vertices
    point = Constraint(ConstraintKind.FORCE, "P", ("P:Vertex3",), points=(Vec3(0, 0, 0),))
    assert distance_to_constraint(Vec3(3, 4, 0), point) == 5.0


def test_load_on_two_separate_faces_gets_one_anchor_on_each_never_in_the_air():
    # Owner's model: one force on two faces of different plates. Their common
    # centroid is in the air; the balloon must point at each face instead.
    from freecad.PartReview.domain.geometry import point_triangle_distance
    a = square(0.0)  # face at x = 0, 0..1 in y and z
    b = tuple(tuple(Vec3(p.z + 5.0, 3.0, p.y) for p in tri) for tri in square(0.0))  # y = 3
    load = Constraint(ConstraintKind.FORCE, "ConstraintForce", ("P:Face4", "P:Face38"),
                      geometry=a + b)
    spot = constraint_hotspot(load)
    assert len(spot.anchors) == 2
    for anchor in spot.anchors:
        assert min(point_triangle_distance(anchor, *tri) for tri in a + b) < 1e-9
    assert spot.center in spot.anchors


def test_support_on_hole_edges_gets_an_anchor_on_each_edge():
    import math
    def circle(cx, n=12):
        pts = [Vec3(cx + math.cos(2 * math.pi * k / n), math.sin(2 * math.pi * k / n), 0.0)
               for k in range(n + 1)]
        return tuple(zip(pts, pts[1:]))
    fixed = Constraint(ConstraintKind.FIXED, "ConstraintFixed", ("P:Edge19", "P:Edge20"),
                       lines=circle(0.0) + circle(10.0))
    spot = constraint_hotspot(fixed)
    assert spot.kind is HotspotKind.SUPPORT and len(spot.anchors) == 2
    for anchor in spot.anchors:  # on a circle of radius 1 around x = 0 or x = 10
        cx = 0.0 if anchor.x < 5 else 10.0
        assert math.hypot(anchor.x - cx, anchor.y) == pytest.approx(1.0, abs=0.05)


def test_figure_markers_follow_visible_leaders_and_kind():
    from dataclasses import replace
    from freecad.PartReview.domain.camera_planner import CameraSpec, PlannedView
    from freecad.PartReview.domain.i18n import Translator
    from freecad.PartReview.domain.report import _figure
    from test_i18n_report import make_inputs
    a = square(0.0)
    b = tuple(tuple(Vec3(p.z + 5.0, 3.0, p.y) for p in tri) for tri in square(0.0))
    load = constraint_hotspot(Constraint(ConstraintKind.FORCE, "F", ("P:Face1", "P:Face2"),
                                         geometry=a + b))
    cam = CameraSpec(direction=Vec3(0, 0, -1), up=Vec3(0, 1, 0), center=Vec3(2.5, 1.5, 0.5),
                     height=10.0, distance=50.0, near=1.0, far=100.0)
    inputs = make_inputs()
    numbers = {load: 3}
    both = PlannedView(cam, FieldKind.VON_MISES, (load,), leaders=(load.anchors,))
    fig = _figure(0, both, inputs, numbers, Translator("pt_BR", strict=True))
    m = fig.markers[0]
    assert m.number == 3 and m.style == "load" and len(m.more) == 1
    assert "laranja" in fig.balloons
    one = replace(both, leaders=(load.anchors[:1],))
    assert _figure(0, one, inputs, numbers, Translator("en", strict=True)).markers[0].more == ()
    hidden = replace(both, leaders=((),))
    assert _figure(0, hidden, inputs, numbers, Translator("en", strict=True)).markers == ()
