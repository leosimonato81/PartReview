# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Mesh options for a solid, from its geometry only (pure, no Qt).

Starting points (practical FEM rules), not verdicts: each option says why.
- coarse: about 1 quadratic element across the characteristic thickness (h = t);
- medium: about 2 (h = t/2); fine: about 3 (h = t/3);
- chunky parts (t close to the part size) are capped by the bounding-box
  diagonal D: h <= D/10, D/20, D/30, so a solid block still gets a usable mesh.
Always 2nd order and curvature-based sizing (FreeCAD default 12): in spike 8.0
coarse meshes WITHOUT curvature produced inverted 2nd-order elements that
CalculiX refused; with curvature 12 the same sizes ran.
"""

import math
from dataclasses import dataclass
from enum import Enum

from .geometry_summary import GeometrySummary

CURVATURE = 12  # Gmsh "elements per 2*pi radians" (FreeCAD default, spike 8.0)
TETS_PER_UNIT_VOLUME = 6.0 * math.sqrt(2.0)  # regular tetrahedron of edge h: V = h^3/(6 sqrt 2)
# Spike 8.0: real meshes had 1.9x (no curvature) to 5.5x (curvature, small holes) the
# tetrahedra of the regular-tet formula, and ~1.75 nodes per 2nd-order tetrahedron.
TET_FACTOR_LOW, TET_FACTOR_HIGH = 2.0, 6.0
NODES_PER_TET = 1.75


class MeshLevel(Enum):
    COARSE = "coarse"
    MEDIUM = "medium"
    FINE = "fine"


_DIVISOR = {MeshLevel.COARSE: 1, MeshLevel.MEDIUM: 2, MeshLevel.FINE: 3}
_DIAGONAL_RATIO = 10.0


@dataclass(frozen=True)
class MeshOption:
    level: MeshLevel
    max_size: float  # mm -> Gmsh CharacteristicLengthMax
    min_size: float  # mm -> CharacteristicLengthMin (0 = Gmsh decides)
    curvature: int  # -> MeshSizeFromCurvature
    order: str  # -> ElementOrder
    reason_key: str  # i18n key explaining max_size
    nodes_low: int  # rough range before meshing (the real count comes from Gmsh)
    nodes_high: int


def estimate_nodes(volume: float, size: float, factor: float) -> int:
    if size <= 0:
        return 0
    return int(volume * TETS_PER_UNIT_VOLUME / size ** 3 * factor * NODES_PER_TET)


def _round_size(value: float) -> float:
    """Two significant digits, so the numbers in the panel are easy to read."""
    if value <= 0:
        return 0.0
    digits = 1 - int(math.floor(math.log10(value)))
    return round(value, digits)


def mesh_options(summary: GeometrySummary) -> list:
    t, diagonal = summary.characteristic_thickness, summary.diagonal
    options = []
    for level in MeshLevel:
        k = _DIVISOR[level]
        by_thickness, by_size = t / k, diagonal / (_DIAGONAL_RATIO * k)
        size = _round_size(min(by_thickness, by_size))
        key = "mesh.reason.thickness" if by_thickness <= by_size else "mesh.reason.diagonal"
        options.append(MeshOption(
            level, size, 0.0, CURVATURE, "2nd", key,
            estimate_nodes(summary.volume, size, TET_FACTOR_LOW),
            estimate_nodes(summary.volume, size, TET_FACTOR_HIGH)))
    return options
