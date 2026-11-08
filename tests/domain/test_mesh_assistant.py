# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import pytest

from freecad.PartReview.domain.geometry_summary import (
    GeometrySummary,
    IssueKind,
    WallSample,
    find_issues,
)
from freecad.PartReview.domain.gmsh_log import parse_gmsh_log
from freecad.PartReview.domain.mesh_sizing import MeshLevel, mesh_options, with_straight_edges

# Owner's part (spike 8.0, "Shroud 001"): real numbers from the geometry inventory.
SHROUD = GeometrySummary(
    name="Cut010", label="Shroud 001", size=(54.3, 59.759, 50.5), volume=18367.382,
    area=12111.945, faces=75, edges=198,
    shortest_edges=((0.4251, "Edge78"), (0.4251, "Edge85"), (0.5782, "Edge80")),
    radii=tuple((0.4, "Face%d" % i) for i in (10, 12, 43, 45, 48, 49, 52, 53, 56, 57))
    + ((1.5, "Face20"), (5.0, "Face30")),
    walls=(WallSample(0.3, ("Face5", "Face71")), WallSample(0.6, ("Face5", "Face11")),
           WallSample(1.7, ("Face38", "Face55")), WallSample(2.0, ("Face30", "Face60"))))


def box(x, y, z, name="Box"):
    return GeometrySummary(name, name, (x, y, z), x * y * z, 2 * (x * y + y * z + x * z), 6, 12,
                           shortest_edges=((min(x, y, z), "Edge1"),),
                           walls=(WallSample(min(x, y, z), ("Face1", "Face2")),))


def test_characteristic_thickness():
    assert SHROUD.characteristic_thickness == pytest.approx(3.033, abs=0.001)
    plate = box(200, 100, 2)
    assert plate.characteristic_thickness == pytest.approx(2.0, rel=0.05)  # plate: = t


def test_owner_part_issues():
    issues = find_issues(SHROUD)
    kinds = [i.kind for i in issues]
    assert kinds == [IssueKind.THIN_WALL, IssueKind.THIN_WALL, IssueKind.SMALL_RADIUS]
    assert issues[0].size == 0.3 and issues[0].elements == ("Face5", "Face71")
    assert issues[2].count == 10 and issues[2].size == 0.4
    assert not any(i.kind is IssueKind.TINY_EDGE for i in issues)  # 0.43 mm > t/10


def test_owner_part_options_match_the_spike_runs():
    sizes = {o.level: o.max_size for o in mesh_options(SHROUD)}
    # spike 8.0: 3 mm and 1.5 mm with curvature 12 ran (56k and 95k nodes);
    # ~1 mm needed > 4.5 GB on the reference PC.
    assert sizes == {MeshLevel.COARSE: 3.0, MeshLevel.MEDIUM: 1.5, MeshLevel.FINE: 1.0}
    coarse = mesh_options(SHROUD)[0]
    assert coarse.curvature == 12 and coarse.order == "2nd" and coarse.min_size == 0.0
    assert coarse.nodes_low <= 56445 <= coarse.nodes_high


@pytest.mark.parametrize("scale", [0.01, 1.0, 100.0])
def test_rules_scale_with_the_part(scale):
    small, large = box(10, 10, 10), box(10 * scale, 10 * scale, 10 * scale)
    for a, b in zip(mesh_options(small), mesh_options(large)):
        assert b.max_size == pytest.approx(a.max_size * scale, rel=0.05)
        assert b.nodes_high == pytest.approx(a.nodes_high, rel=0.15)


def test_chunky_parts_are_capped_by_the_diagonal():
    cube = mesh_options(box(100, 100, 100))
    assert cube[0].reason_key == "mesh.reason.diagonal"
    assert cube[0].max_size == pytest.approx(17, abs=0.5)  # D/10 = 17.3
    plate = mesh_options(box(200, 100, 2))
    assert plate[0].reason_key == "mesh.reason.thickness"
    assert [o.max_size for o in plate] == [1.9, 0.97, 0.65]


def test_options_get_finer_and_bigger():
    options = mesh_options(SHROUD)
    assert options[0].max_size > options[1].max_size > options[2].max_size
    assert options[0].nodes_high < options[1].nodes_high < options[2].nodes_high


LOG_COARSE = """Info    : Done meshing 2D (Wall 0.759963s, CPU 5.53424s)
Info    : Done meshing 3D (Wall 0.201727s, CPU 0.297238s)
Warning : Surface mesh: worst distortion = -1.02541 (avg = 0.9785, 1 elements with jac. < 0); worst gamma = 0.0420559
Warning : Volume mesh: worst distortion = -1.70065 (avg = 0.963775, 9 elements with jac. < 0)
Info    : Done meshing order 2 (Wall 0.206071s, CPU 0.205055s)
Info    : 21602 nodes 18785 elements
"""
LOG_OWNER = """Info    : Done meshing 3D (Wall 3.06303s, CPU 3.114s)
Info    : Volume mesh: worst distortion = 0.00283241 (8 elements in ]0, 0.2])
Info    : 191066 nodes 155896 elements
"""


def test_parse_gmsh_log():
    run = parse_gmsh_log(LOG_COARSE)
    assert (run.nodes, run.elements, run.inverted) == (21602, 18785, 9)
    assert run.finished and dict(run.stage_seconds)["meshing 2D"] == pytest.approx(0.76, abs=0.01)
    good = parse_gmsh_log(LOG_OWNER)
    assert good.nodes == 191066 and good.inverted == 0
    broken = parse_gmsh_log("Error   : Unable to recover the edge 12\n")
    assert not broken.finished and broken.errors


# Real node counts from the assistant tests in FreeCAD (curvature 12, 2nd order).
@pytest.mark.parametrize("summary, level, nodes", [
    (SHROUD, 0, 57285), (SHROUD, 1, 98723), (SHROUD, 2, 198495),
    (box(1000, 1000, 1000), 0, 2492), (box(1000, 1000, 1000), 2, 41524),
    (box(8000, 1000, 1000), 0, 1448), (box(8000, 1000, 1000), 2, 16277)])
def test_real_node_counts_fall_in_the_estimated_range(summary, level, nodes):
    option = mesh_options(summary)[level]
    assert option.nodes_low <= nodes <= option.nodes_high


def test_straight_edges_fallback_keeps_the_size():
    coarse = mesh_options(SHROUD)[0]
    fixed = with_straight_edges(coarse)
    assert fixed.straight_edges and not coarse.straight_edges
    assert fixed.max_size == coarse.max_size and fixed.level is coarse.level
