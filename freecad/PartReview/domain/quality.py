# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Equilibrium check and mesh indicators (decisions 004 and 005).

Only quantities with a mathematical or physical basis:
- static equilibrium: sum of applied forces + sum of support reactions = 0;
- tetrahedron radius ratio rho = 3 r_in / R_circ (1 = regular, 0 = degenerate;
  Shewchuk, "What Is a Good Linear Finite Element?", 2002);
- inverted/degenerate elements: corner volume of the wrong sign or zero.
No pass/fail thresholds are invented for rho: statistics only.
"""

import math
import re
from dataclasses import dataclass
from enum import Enum

from . import geometry as g
from .models import Vec3

EQUILIBRIUM_TOLERANCE = 1e-3  # relative; the solver balances to ~1e-12 (decision 004)


class EquilibriumStatus(Enum):
    VERIFIED = "verified"
    IMBALANCE = "imbalance"
    NOT_VERIFIABLE = "not_verifiable"  # load types we do not sum (pressure, gravity...)
    NOT_AVAILABLE = "not_available"  # no reaction data (no ccx_dat_file)


@dataclass(frozen=True)
class EquilibriumCheck:
    status: EquilibriumStatus
    applied: Vec3 | None = None  # N
    reactions: Vec3 | None = None  # N
    residual: float | None = None  # |applied + reactions| / |applied|
    reason_key: str = ""  # i18n key explaining NOT_VERIFIABLE / NOT_AVAILABLE
    # Part of the applied load that sits on fixed nodes (N). CalculiX leaves it out of
    # the reaction totals (it goes straight into the support), so it is added back.
    load_on_supports: Vec3 | None = None


_TOTAL = re.compile(r"total force \(fx,fy,fz\) for set (\S+) and time\s+(\S+)")


def parse_ccx_totals(text: str) -> dict:
    """{set name: Vec3} from CalculiX .dat 'total force' blocks (last time wins)."""
    totals = {}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        match = _TOTAL.search(line)
        if not match:
            continue
        for following in lines[i + 1:]:
            parts = following.split()
            if len(parts) == 3:
                try:
                    totals[match.group(1)] = Vec3(*(float(p) for p in parts))
                except ValueError:
                    continue
                break
            if parts:
                break
    return totals


def check_equilibrium(applied: Vec3, reactions: Vec3,
                      tolerance: float = EQUILIBRIUM_TOLERANCE,
                      load_on_supports: Vec3 | None = None) -> EquilibriumCheck:
    """Applied forces + support reactions = 0.

    ``reactions`` are CalculiX totals (*NODE PRINT ... TOTALS). Loads applied on
    nodes that are themselves fixed never show up there: the support takes them
    directly. ``load_on_supports`` (their sum) is subtracted from the reported
    reactions, so the support reaction is complete (spike 8.0, decision 007).
    """
    magnitude = g.length(applied)
    if magnitude == 0:
        return EquilibriumCheck(EquilibriumStatus.NOT_VERIFIABLE, applied, reactions,
                                reason_key="eq.reason.no_load")
    if load_on_supports is not None:
        reactions = g.sub(reactions, load_on_supports)
    residual = g.length(g.add(applied, reactions)) / magnitude
    status = EquilibriumStatus.VERIFIED if residual <= tolerance else EquilibriumStatus.IMBALANCE
    return EquilibriumCheck(status, applied, reactions, residual,
                            load_on_supports=load_on_supports)


def load_on_fixed_nodes(node_loads, fixed_nodes) -> Vec3:
    """Sum of nodal loads {node: Vec3 in N} on nodes listed in ``fixed_nodes``."""
    total = Vec3(0.0, 0.0, 0.0)
    for node, load in node_loads.items():
        if node in fixed_nodes:
            total = g.add(total, load)
    return total


# --- mesh shape ----------------------------------------------------------------

def signed_volume(a: Vec3, b: Vec3, c: Vec3, d: Vec3) -> float:
    return g.dot(g.sub(b, a), g.cross(g.sub(c, a), g.sub(d, a))) / 6.0


def radius_ratio(a: Vec3, b: Vec3, c: Vec3, d: Vec3) -> float:
    """3 r_in / R_circ of a tetrahedron: 1 for the regular one, 0 when degenerate."""
    volume = abs(signed_volume(a, b, c, d))
    if volume == 0:
        return 0.0
    faces = ((a, b, c), (a, b, d), (a, c, d), (b, c, d))
    area = sum(g.length(g.cross(g.sub(q, p), g.sub(r, p))) / 2.0 for p, q, r in faces)
    r_in = 3.0 * volume / area
    u, v, w = g.sub(b, a), g.sub(c, a), g.sub(d, a)
    num = g.add(g.add(g.scale(g.cross(v, w), g.dot(u, u)), g.scale(g.cross(w, u), g.dot(v, v))),
                g.scale(g.cross(u, v), g.dot(w, w)))
    r_circ = g.length(num) / (12.0 * volume)
    return min(1.0, 3.0 * r_in / r_circ)


def _percentile(sorted_values, fraction):
    if not sorted_values:
        return float("nan")
    k = (len(sorted_values) - 1) * fraction
    lo, hi = math.floor(k), math.ceil(k)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


@dataclass(frozen=True)
class MeshQuality:
    nodes_per_element: int
    element_count: int
    invalid_elements: int  # corner volume of the wrong sign or zero
    ratio_min: float
    ratio_p5: float
    ratio_median: float
    histogram: tuple[int, ...]  # 10 bins of rho: [0, 0.1), ..., [0.9, 1.0]
    mean_edge: float  # mesh length unit
    edge_at_max: float | None = None  # mean edge of the elements around the max-stress node


def mesh_quality(elements, positions, max_node: int | None = None) -> MeshQuality:
    """Shape statistics of tetrahedral elements (corner nodes)."""
    ratios, volumes, edges_all = [], [], []
    edges_at_max = []
    for element in elements:
        a, b, c, d = (positions[n] for n in element[:4])
        volumes.append(signed_volume(a, b, c, d))
        ratios.append(radius_ratio(a, b, c, d))
        corners = (a, b, c, d)
        lengths = [g.distance(corners[i], corners[j]) for i in range(4) for j in range(i + 1, 4)]
        edges_all.extend(lengths)
        if max_node is not None and max_node in element:
            edges_at_max.extend(lengths)
    positive = sum(1 for v in volumes if v > 0)
    prevailing = 1.0 if positive >= len(volumes) - positive else -1.0
    invalid = sum(1 for v in volumes if v * prevailing <= 0)
    histogram = [0] * 10
    for r in ratios:
        histogram[min(9, int(r * 10))] += 1
    ordered = sorted(ratios)
    return MeshQuality(
        nodes_per_element=len(elements[0]) if elements else 0,
        element_count=len(elements),
        invalid_elements=invalid,
        ratio_min=ordered[0] if ordered else float("nan"),
        ratio_p5=_percentile(ordered, 0.05),
        ratio_median=_percentile(ordered, 0.5),
        histogram=tuple(histogram),
        mean_edge=sum(edges_all) / len(edges_all) if edges_all else float("nan"),
        edge_at_max=sum(edges_at_max) / len(edges_at_max) if edges_at_max else None,
    )


@dataclass(frozen=True)
class ErrorEstimate:
    """Zienkiewicz-Zhu estimate (decision 005) or the reason it is not available."""

    available: bool
    relative_error: float = 0.0  # global, energy norm, 0..1
    max_local: float = 0.0
    p95_local: float = 0.0
    invalid_jacobian: int = 0
    reason_key: str = ""


STRESS_FRACTIONS = (0.5, 0.8, 1.0)


def volume_above(elements, positions, stress_by_node, limit: float,
                 fractions=STRESS_FRACTIONS) -> list[tuple[float, float]]:
    """[(fraction, share of the part's volume whose stress >= fraction x limit)].

    Element stress = mean of its nodal values; element volume from its 4 corner
    nodes (exact for straight-sided tetrahedra). A peak on a few elements and a
    large loaded region can have the same maximum: this tells them apart.
    """
    total = 0.0
    above = [0.0] * len(fractions)
    for element in elements:
        a, b, c, d = (positions[n] for n in element[:4])
        volume = abs(g.dot(g.sub(b, a), g.cross(g.sub(c, a), g.sub(d, a)))) / 6.0
        values = [stress_by_node[n] for n in element if n in stress_by_node]
        if not values:
            continue
        mean = sum(values) / len(values)
        total += volume
        for i, f in enumerate(fractions):
            if mean >= f * limit:
                above[i] += volume
    if total <= 0 or limit <= 0:
        return []
    return [(f, v / total) for f, v in zip(fractions, above)]
