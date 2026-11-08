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
    assert spot.center == pytest.approx(Vec3(0.0, 0.5, 0.5))
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
