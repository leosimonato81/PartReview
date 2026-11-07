# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import math

import pytest

from freecad.PartReview.domain.models import Vec3
from freecad.PartReview.domain.quality import (
    EquilibriumStatus,
    check_equilibrium,
    load_on_fixed_nodes,
    mesh_quality,
    parse_ccx_totals,
    radius_ratio,
    signed_volume,
)

# Real text from a.FCStd and from the native cantilever example (decision 004).
DAT_A = """
                        S T E P       1


                                INCREMENT     1


 total force (fx,fy,fz) for set CONSTRAINTFIXED and time  0.1000000E+01

       -7.507241E-13 -7.697732E-12  1.643262E+01
"""
DAT_CANTILEVER = """
 total force (fx,fy,fz) for set CONSTRAINTFIXED and time  0.1000000E+01

        1.192093E-06 -3.371388E-07  9.000000E+06
"""


def test_parse_ccx_totals():
    totals = parse_ccx_totals(DAT_A)
    assert list(totals) == ["CONSTRAINTFIXED"]
    assert totals["CONSTRAINTFIXED"].z == pytest.approx(16.43262)
    assert parse_ccx_totals("no totals here") == {}


def test_equilibrium_verified_on_the_cantilever():
    reactions = parse_ccx_totals(DAT_CANTILEVER)["CONSTRAINTFIXED"]
    check = check_equilibrium(Vec3(0.0, 0.0, -9e6), reactions)
    assert check.status is EquilibriumStatus.VERIFIED
    assert check.residual < 1e-9


def test_equilibrium_imbalance_on_a_fcstd():
    reactions = parse_ccx_totals(DAT_A)["CONSTRAINTFIXED"]
    check = check_equilibrium(Vec3(0.0, 0.0, -18.0), reactions)
    assert check.status is EquilibriumStatus.IMBALANCE
    assert check.residual == pytest.approx((18.0 - 16.43262) / 18.0, rel=1e-6)


# Spike 8.0 (decision 007), a (Copy).FCStd remeshed at 3 mm + curvature 12: the load
# faces touch the fixed face; CalculiX reaction totals miss the load on shared nodes.
DAT_SPIKE = """
 total force (fx,fy,fz) for set CONSTRAINTFIXED and time  0.1000000E+01

       -1.0E-13  2.0E-12  1.719600E+01
"""


def test_load_on_fixed_nodes_closes_the_balance():
    reactions = parse_ccx_totals(DAT_SPIKE)["CONSTRAINTFIXED"]
    applied = Vec3(0.0, 0.0, -18.0)
    assert check_equilibrium(applied, reactions).status is EquilibriumStatus.IMBALANCE
    on_supports = Vec3(0.0, 0.0, -0.8040)  # sum of *CLOAD on fixed nodes (39 nodes)
    check = check_equilibrium(applied, reactions, load_on_supports=on_supports)
    assert check.status is EquilibriumStatus.VERIFIED
    assert check.reactions.z == pytest.approx(18.0)
    assert check.load_on_supports == on_supports


def test_load_on_fixed_nodes_sums_only_fixed_ones():
    loads = {1: Vec3(0, 0, -1.0), 2: Vec3(0, 0, -2.0), 3: Vec3(1.0, 0, -4.0)}
    assert load_on_fixed_nodes(loads, {2, 3, 99}) == Vec3(1.0, 0.0, -6.0)
    assert load_on_fixed_nodes(loads, set()) == Vec3(0.0, 0.0, 0.0)


def test_a_real_imbalance_is_still_reported():
    reactions = parse_ccx_totals(DAT_SPIKE)["CONSTRAINTFIXED"]
    check = check_equilibrium(Vec3(0.0, 0.0, -18.0), reactions,
                              load_on_supports=Vec3(0.0, 0.0, 0.0))
    assert check.status is EquilibriumStatus.IMBALANCE


def test_equilibrium_without_load_is_not_verifiable():
    check = check_equilibrium(Vec3(0, 0, 0), Vec3(0, 0, 1))
    assert check.status is EquilibriumStatus.NOT_VERIFIABLE


REGULAR = (Vec3(1, 1, 1), Vec3(1, -1, -1), Vec3(-1, 1, -1), Vec3(-1, -1, 1))


def test_radius_ratio_regular_and_degenerate():
    assert radius_ratio(*REGULAR) == pytest.approx(1.0)
    flat = (Vec3(0, 0, 0), Vec3(1, 0, 0), Vec3(0, 1, 0), Vec3(1, 1, 1e-9))
    assert radius_ratio(*flat) < 1e-6
    corner = (Vec3(0, 0, 0), Vec3(1, 0, 0), Vec3(0, 1, 0), Vec3(0, 0, 1))
    # right-corner tetrahedron: rho = 3 r_in / R = 3*(1/(3+sqrt3)) / (sqrt3/2)
    assert radius_ratio(*corner) == pytest.approx(3 * (1 / (3 + math.sqrt(3))) / (math.sqrt(3) / 2))


def test_mesh_quality_counts_inverted_elements_and_bins():
    pos = {1: Vec3(0, 0, 0), 2: Vec3(1, 0, 0), 3: Vec3(0, 1, 0), 4: Vec3(0, 0, 1),
           5: Vec3(1, 1, 1)}
    good = (1, 2, 3, 4)
    inverted = (1, 3, 2, 4)
    assert signed_volume(*(pos[n] for n in good)) > 0 > signed_volume(*(pos[n] for n in inverted))
    q = mesh_quality([good, good, inverted], pos, max_node=1)
    assert q.invalid_elements == 1
    assert sum(q.histogram) == 3
    assert q.ratio_min == pytest.approx(q.ratio_median)
    assert q.edge_at_max == pytest.approx(q.mean_edge)
    assert q.nodes_per_element == 4
