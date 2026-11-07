# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import pytest

from freecad.PartReview.domain.fem_rules import constraint_kind, element_order
from freecad.PartReview.domain.models import ConstraintKind


@pytest.mark.parametrize("dimension, nodes, order", [
    (3, 4, 1), (3, 10, 2), (3, 8, 1), (3, 20, 2),
    (2, 3, 1), (2, 6, 2),
    (1, 2, 1), (1, 3, 2),
])
def test_element_order(dimension, nodes, order):
    assert element_order(dimension, nodes) == order


def test_element_order_unknown_raises():
    with pytest.raises(ValueError):
        element_order(3, 7)


def test_constraint_kind():
    assert constraint_kind("Fem::ConstraintFixed") is ConstraintKind.FIXED
    assert constraint_kind("Fem::ConstraintForce") is ConstraintKind.FORCE
    assert constraint_kind("Fem::ConstraintTemperature") is ConstraintKind.OTHER
    assert constraint_kind("Fem::FemMeshObjectPython") is None


@pytest.mark.parametrize("analysis, eigenmode, ok", [
    ("static", 0, True),
    ("", 0, True),            # no solver object: accepted unless it is a mode
    ("frequency", 0, False),
    ("buckling", 0, False),
    ("thermomech", 0, False),
    ("static", 1, False),     # an eigenmode is never a static result
    ("", 3, False),
])
def test_only_linear_static_results_are_supported(analysis, eigenmode, ok):
    from freecad.PartReview.domain.fem_rules import is_supported_analysis
    assert is_supported_analysis(analysis, eigenmode) is ok
