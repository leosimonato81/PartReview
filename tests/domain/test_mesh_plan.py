# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import pytest

from freecad.PartReview.domain import solver_probe as sp
from freecad.PartReview.domain.mesh_plan import (
    Objective,
    REFERENCE,
    nodes_law,
    part_model,
    probe_allowed,
    size_for_nodes,
    target_nodes,
)
from freecad.PartReview.domain.solver_model import SolverSample

GEO = '''General.NumThreads = 8;
Merge "Fillet004_Geometry.brep";
Physical Line("Edge1") = {1};
Physical Surface("Face1") = {1};
Physical Volume("Solid1") = {1};
Mesh.CharacteristicLengthMax = 3.0;
Mesh.ElementOrder = 2;
Mesh  3;
Mesh.SaveGroupsOfNodes = 1;
Mesh.SaveAll = 1;
Save "Fillet004_Mesh.unv";
'''


def test_probe_geo_keeps_settings_and_saves_only_the_volume():
    geo = sp.probe_geo(GEO, "probe.inp")
    assert "Physical Line" not in geo and "Physical Surface" not in geo
    assert 'Physical Volume("PROBE_SOLID") = {1};' in geo
    assert "Mesh.CharacteristicLengthMax = 3.0;" in geo and "Mesh.SaveAll = 0;" in geo
    assert 'Save "probe.inp";' in geo and ".unv" not in geo


def test_probe_deck_clamps_one_end_and_loads_the_other():
    nodes = {i: (float(x), 0.0, float(z)) for i, (x, z) in enumerate(
        [(0, 0), (0, 5), (0, 10), (50, 5), (100, 0), (100, 10)], start=1)}
    fixed, loaded, axis = sp.end_slabs(nodes)
    assert axis == 0 and fixed == [1, 2, 3] and loaded == [5, 6]
    deck = sp.solver_deck("m.inp", nodes)
    assert "ELSET=PROBE_SOLID" in deck and "5, 3, -500" in deck


# Owner's part on the reference PC (spike 8.0): probes at 56 445 and 95 129 nodes.
OWNER = [SolverSample(56445, 10.5, 1029.0), SolverSample(95129, 27.6, 2082.0)]


def test_part_model_from_probes():
    model = part_model(OWNER)
    assert model.measured and model.memory_mb(56445) == pytest.approx(1029, rel=1e-6)
    one = part_model(OWNER[:1])  # one point: reference exponent through it
    assert one.memory_mb(56445) == pytest.approx(1029, rel=1e-6) and one.error == 0.4
    assert part_model([]) is REFERENCE
    tiny = part_model([SolverSample(3000, 0.4, 60.0)])  # below the fit threshold
    assert tiny.measured


def test_objectives_order_and_safety():
    model = part_model(OWNER)
    free = 4000.0
    n = {o: target_nodes(model, free, o, 0.6) for o in Objective}
    assert n[Objective.MIN_1] <= n[Objective.MIN_5] <= n[Objective.MIN_10]
    assert all(n[o] <= n[Objective.MEMORY] for o in Objective)  # memory always applies
    for o in Objective:
        assert model.memory_mb(n[o]) * (1 + model.error) <= 0.6 * free + 1e-6


def test_probe_is_refused_when_too_heavy():
    model = part_model(OWNER)
    assert probe_allowed(model, 56445, 4000.0)
    assert not probe_allowed(model, 183059, 4000.0)


def test_size_for_a_target_node_count():
    trials = [(3.0, 57285), (1.5, 98723), (1.0, 198495)]  # owner's part, real Gmsh runs
    law = nodes_law(trials)
    assert law.exponent < 0
    size = size_for_nodes(law, 120000)
    assert 1.0 < size < 1.5


def test_classify_uses_measured_value_or_safe_prediction():
    from freecad.PartReview.domain.mesh_budget import BudgetStatus
    from freecad.PartReview.domain.mesh_plan import classify
    model = part_model(OWNER)  # error 30 %
    assert classify(model, 56445, 4000.0, measured_mb=1029.0) is BudgetStatus.FITS
    # 95 129 nodes: measured 2.08 GB -> fits under 60 % of 4 GB? 2082 <= 2400 yes
    assert classify(model, 95129, 4000.0, measured_mb=2082.0) is BudgetStatus.FITS
    # predicted with +30 %: 2.7 GB -> tight
    assert classify(model, 95129, 4000.0) is BudgetStatus.TIGHT
    assert classify(model, 183059, 4000.0) is BudgetStatus.TOO_BIG


def test_binding_limit():
    from freecad.PartReview.domain.mesh_plan import binding_limit
    model = part_model(OWNER)
    assert binding_limit(model, 4000.0, Objective.MEMORY, 0.6) == "memory"
    assert binding_limit(model, 4000.0, Objective.MIN_10, 0.6) == "memory"  # 8 GB PC
    assert binding_limit(model, 400000.0, Objective.MIN_1, 0.6) == "time"  # huge RAM


def test_probe_planning_margin_is_capped():
    one_point = part_model(OWNER[:1])  # error 40 %
    # 56 445 nodes measured 1.0 GB: a probe up to 50 % of 2.9 GB free is allowed
    # with the 25 % planning margin (the 65 % watchdog is the hard stop)
    assert probe_allowed(one_point, 56445, 2900.0)


def test_recommendation_prefers_two_elements_across_the_wall():
    from freecad.PartReview.domain.mesh_budget import BudgetStatus as B
    from freecad.PartReview.domain.mesh_plan import recommend
    from freecad.PartReview.domain.mesh_sizing import MeshLevel as L
    fits = {L.VERY_COARSE: B.FITS, L.COARSE: B.FITS, L.MEDIUM: B.FITS, L.FINE: B.TOO_BIG}
    assert recommend(fits, {})[0] is L.MEDIUM
    all_fit = {**fits, L.FINE: B.FITS}
    assert recommend(all_fit, {L.FINE: 60.0})[0] is L.FINE
    assert recommend(all_fit, {L.FINE: 600.0})[0] is L.MEDIUM  # too slow for the default
    tight = {L.VERY_COARSE: B.FITS, L.COARSE: B.FITS, L.MEDIUM: B.TIGHT}
    assert recommend(tight, {}) == (L.COARSE, "ma.recommend.coarse")


def test_total_time_includes_freecad_overhead():
    from freecad.PartReview.domain.mesh_plan import total_seconds
    model = part_model(OWNER)
    # owner's model, 57 299 nodes: CalculiX 11.4 s measured, total ~21 s measured
    assert total_seconds(model, 57299, solver_seconds=11.4) == pytest.approx(21.1, abs=0.2)


def test_options_carry_a_local_refinement_size():
    from test_mesh_assistant import SHROUD
    from freecad.PartReview.domain.mesh_sizing import mesh_options
    for option in mesh_options(SHROUD):
        assert option.local_size == pytest.approx(option.max_size / 2, rel=0.1)
