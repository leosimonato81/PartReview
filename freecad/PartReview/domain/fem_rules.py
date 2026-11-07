# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Small pure rules about FEM data, kept here so they are unit-tested."""

from .models import ConstraintKind

# Nodes per element -> element order, by element dimension.
_ORDER_BY_NODES = {
    3: {4: 1, 10: 2, 8: 1, 20: 2, 6: 1, 15: 2, 5: 1, 13: 2},  # tet, hex, wedge, pyramid
    2: {3: 1, 6: 2, 4: 1, 8: 2},  # tria, quad
    1: {2: 1, 3: 2},  # beam
}

# FreeCAD constraint TypeId -> our constraint kind.
_CONSTRAINT_KINDS = {
    "Fem::ConstraintFixed": ConstraintKind.FIXED,
    "Fem::ConstraintForce": ConstraintKind.FORCE,
    "Fem::ConstraintPressure": ConstraintKind.PRESSURE,
    "Fem::ConstraintDisplacement": ConstraintKind.DISPLACEMENT,
}


def element_order(dimension: int, nodes_per_element: int) -> int:
    """1 (linear) or 2 (quadratic). Raises ValueError for unknown elements."""
    try:
        return _ORDER_BY_NODES[dimension][nodes_per_element]
    except KeyError:
        raise ValueError("unknown element: dimension=%r nodes=%r"
                         % (dimension, nodes_per_element)) from None


def constraint_kind(type_id: str) -> ConstraintKind | None:
    """Kind for a FreeCAD constraint TypeId; None if it is not a constraint."""
    if type_id in _CONSTRAINT_KINDS:
        return _CONSTRAINT_KINDS[type_id]
    if type_id.startswith("Fem::Constraint"):
        return ConstraintKind.OTHER
    return None


# v1.3.0 reports linear static results only. CalculiX frequency (modal) and
# buckling results are also stored as mechanical results, with an eigenmode
# number > 0; reporting them as stresses under load would be misleading.
SUPPORTED_ANALYSIS_TYPES = ("static",)


def is_supported_analysis(analysis_type: str, eigenmode: int = 0) -> bool:
    """True for linear static results. An unknown type ("") is accepted only
    when the result is not an eigenmode."""
    if eigenmode and eigenmode > 0:
        return False
    return analysis_type in SUPPORTED_ANALYSIS_TYPES or analysis_type == ""
