# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Mesh options for a solid, from its geometry only (pure, no Qt).

Starting points (practical FEM rules), not verdicts: each option says why.
- very coarse: h = 1.5 t (quick look, stiffness only);
- coarse: about 1 quadratic element across the characteristic thickness (h = t);
- medium: about 2 (h = t/2); fine: about 3 (h = t/3); very fine: about 4 (h = t/4);
- chunky parts (t close to the part size) are capped by the bounding-box
  diagonal D: h <= D/10, D/20, D/30, so a solid block still gets a usable mesh.
Local regions: supports/loads at h/2; holes and fillets at about r/5 (never
finer than h/4), where stress concentrates (radius_regions).
Always 2nd order (straight sides only as a fallback, see with_straight_edges) and
curvature-based sizing (FreeCAD default 12): in spike 8.0
coarse meshes WITHOUT curvature produced inverted 2nd-order elements that
CalculiX refused; with curvature 12 the same sizes ran.
"""

import math
from dataclasses import dataclass, replace
from enum import Enum

from .geometry_summary import GeometrySummary

CURVATURE = 12  # Gmsh "elements per 2*pi radians" (FreeCAD default, spike 8.0)
TETS_PER_UNIT_VOLUME = 6.0 * math.sqrt(2.0)  # regular tetrahedron of edge h: V = h^3/(6 sqrt 2)
# Real Gmsh meshes (2nd order, curvature 12) had 0.5x (plain blocks) to 5.7x (small
# holes and fillets) the nodes of the regular-tetrahedron formula below, with
# ~1.75 nodes per 2nd-order tetrahedron (spike 8.0 and the assistant tests).
TET_FACTOR_LOW, TET_FACTOR_HIGH = 0.5, 6.0
NODES_PER_TET = 1.75


class MeshLevel(Enum):
    VERY_COARSE = "very_coarse"
    COARSE = "coarse"
    MEDIUM = "medium"
    FINE = "fine"
    VERY_FINE = "very_fine"
    AUTO = "auto"  # size computed for an objective (memory or solve time)


_DIVISOR = {MeshLevel.VERY_COARSE: 2.0 / 3.0, MeshLevel.COARSE: 1, MeshLevel.MEDIUM: 2,
            MeshLevel.FINE: 3, MeshLevel.VERY_FINE: 4}
DEFAULT_LEVEL = MeshLevel.MEDIUM  # ~2 elements across the wall (coarse gave 24 % error)
_DIAGONAL_RATIO = 10.0
LOCAL_FACTOR = 0.5  # refined regions use half the global size
# Holes and fillets (faces with a radius): local size ~ r/5. A1 (plate with a hole,
# r = 5 mm, Heywood): a 1 mm region (r/5) with a 2 mm global size gave the peak
# within -0.4 to -1 %; curvature sizing alone at 1.3 mm (24 per turn) missed it by
# up to 2.6 %. Validated on that case only (A2.3 adds more).
RADIUS_FACTOR = 0.2
MIN_LOCAL_RATIO = 0.25  # cost guard: a region is never finer than 1/4 of the global size


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
    # -> SecondOrderLinear. Default True: curved 2nd-order elements folded near small
    # details and refinement regions on every size of the owner's part (each fold cost a
    # second Gmsh run); straight sides never fold, same node count, half the trial time.
    straight_edges: bool = True
    local_size: float = 0.0  # mm, mesh region on supports/loads (0 = none)
    # ((size mm, ("FaceN", ...)), ...): regions on holes and fillets (radius_regions)
    radius_regions: tuple = ()


def radius_regions(radii, max_size: float) -> tuple:
    """Mesh regions for faces with a radius (holes, fillets, bosses): size
    max(r/5, max_size/4), only where r/5 is below the global size. Faces of the same
    size share one region: ((size, ("FaceN", ...)), ...), finest first."""
    groups = {}
    for radius, face in radii:
        if radius <= 0 or RADIUS_FACTOR * radius >= max_size:
            continue
        size = _round_size(max(RADIUS_FACTOR * radius, MIN_LOCAL_RATIO * max_size), 3)
        groups.setdefault(size, []).append(face)
    return tuple((size, tuple(groups[size])) for size in sorted(groups))


def region_groups(option: MeshOption, refine=()) -> dict:
    """{size: [faces]} for one mesh: supports/loads (``refine``) at
    option.local_size plus the option's radius regions; a face in both gets the
    smaller size."""
    by_face = {}
    if option.local_size > 0:
        for face in refine:
            by_face[face] = option.local_size
    for size, faces in option.radius_regions:
        for face in faces:
            by_face[face] = min(size, by_face.get(face, size))
    groups = {}
    for face, size in by_face.items():
        groups.setdefault(size, []).append(face)
    return groups


def auto_option(summary: GeometrySummary, size: float, objective_key: str) -> MeshOption:
    """Option with a size computed for an objective (see mesh_plan)."""
    size = _round_size(size, 3)  # 3 digits: the search needs finer steps than the levels
    n = estimate_nodes(summary.volume, size, 1.0)
    return MeshOption(MeshLevel.AUTO, size, 0.0, CURVATURE, "2nd", objective_key,
                      int(n * TET_FACTOR_LOW), int(n * TET_FACTOR_HIGH),
                      local_size=_round_size(LOCAL_FACTOR * size, 3),
                      radius_regions=radius_regions(summary.radii, size))


def with_straight_edges(option: MeshOption) -> MeshOption:
    """Same option with straight-sided 2nd-order elements.

    Curved 2nd-order elements follow curved surfaces better, but near tiny details
    they can fold (negative Jacobian) and CalculiX refuses them. Straight sides
    remove the fold at the same size (spike 8.0: 1 inverted element -> 0).
    Gmsh's HighOrderOptimize is NOT used: it aborted Gmsh in FreeCAD 1.1.4.
    """
    return replace(option, straight_edges=True)


def estimate_nodes(volume: float, size: float, factor: float) -> int:
    if size <= 0:
        return 0
    return int(volume * TETS_PER_UNIT_VOLUME / size ** 3 * factor * NODES_PER_TET)


def _round_size(value: float, significant: int = 2) -> float:
    """Few significant digits, so the numbers in the panel are easy to read."""
    if value <= 0:
        return 0.0
    digits = significant - 1 - int(math.floor(math.log10(value)))
    return round(value, digits)


def mesh_options(summary: GeometrySummary) -> list:
    t, diagonal = summary.characteristic_thickness, summary.diagonal
    options = []
    for level in _DIVISOR:
        k = _DIVISOR[level]
        by_thickness, by_size = t / k, diagonal / (_DIAGONAL_RATIO * k)
        size = _round_size(min(by_thickness, by_size))
        key = "mesh.reason.thickness" if by_thickness <= by_size else "mesh.reason.diagonal"
        options.append(MeshOption(
            level, size, 0.0, CURVATURE, "2nd", key,
            estimate_nodes(summary.volume, size, TET_FACTOR_LOW),
            estimate_nodes(summary.volume, size, TET_FACTOR_HIGH),
            local_size=_round_size(LOCAL_FACTOR * size),
            radius_regions=radius_regions(summary.radii, size)))
    return options
