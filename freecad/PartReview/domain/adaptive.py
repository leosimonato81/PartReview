# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Mesh refinement driven by the estimated error (decision 008; pure, no Qt).

Zienkiewicz-Zhu h-adaptivity: with N elements and a target global error eta*,
each element may carry the error e_perm = eta* * sqrt((||u||^2 + ||e||^2) / N)
(uniform distribution, the optimal-mesh criterion). An element with error e gets
the new size h_new = h * (e_perm / e)^(1/p), p = 2 for quadratic tetrahedra,
limited to h/2 per pass. FreeCAD refines by CAD face, and a face can be large
(on a beam, five faces are the whole part): each face gets the MEDIAN size its
too-coarse elements ask for, not the worst one. Tested: the worst-element rule
with h/4 took a 5 000-node beam to 184 000 nodes in one pass.
"""

import math
from dataclasses import dataclass

ORDER = 2  # quadratic tetrahedra
MAX_SHRINK = 0.5  # at most 2x smaller per pass (about 8x more elements there)
MIN_GAIN = 0.10  # stop when the error falls by less than 10 % in one pass
MAX_PASSES = 4


def element_ratios(error_sq, energy_sq_total, target):
    """xi_e = e_e / e_perm per element; > 1 means the element is too coarse."""
    n = len(error_sq)
    if n == 0 or target <= 0:
        return []
    error_total = sum(error_sq)
    allowed = target * math.sqrt((energy_sq_total + error_total) / n)
    if allowed <= 0:
        return [0.0] * n
    return [math.sqrt(max(e, 0.0)) / allowed for e in error_sq]


def new_size(size, ratio):
    """Size an element should have for its share of the target error."""
    if ratio <= 1.0:
        return size
    return size * max(MAX_SHRINK, ratio ** (-1.0 / ORDER))


def face_sizes(element_faces, element_sizes, ratios, current, excluded=()):
    """{face: new size} for faces whose elements are too coarse.

    ``element_faces[i]``: CAD faces touched by element i; ``current``: size each
    face has now (region or global); ``excluded``: faces left alone (singular)."""
    requests = {}
    for faces, size, ratio in zip(element_faces, element_sizes, ratios):
        if ratio <= 1.0:
            continue
        target = new_size(size, ratio)
        for face in faces:
            if face not in excluded:
                requests.setdefault(face, []).append(target)
    wanted = {face: _median(sizes) for face, sizes in requests.items()}
    result = {}
    for face, size in wanted.items():
        now = current.get(face, math.inf)
        if size < 0.95 * now:  # only real refinements (5 % hysteresis)
            result[face] = max(size, MAX_SHRINK * now if now != math.inf else size)
    return result


def _median(values):
    values = sorted(values)
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else 0.5 * (values[mid - 1] + values[mid])


@dataclass(frozen=True)
class Pass:
    nodes: int
    error: float  # global estimated error, 0..1
    max_stress: float  # von Mises, MPa (whole part)
    max_stress_regular: float  # von Mises away from singular faces, MPa
    max_displacement: float  # mm
    seconds: float  # total wall time of the pass
    peak_mb: float  # CalculiX peak memory


def stop_reason(history, target):
    """Why to stop after the last pass, or '' to go on."""
    if not history:
        return ""
    last = history[-1]
    if last.error <= target:
        return "target"
    if len(history) > MAX_PASSES:
        return "passes"
    if len(history) >= 2 and last.error > (1.0 - MIN_GAIN) * history[-2].error:
        return "stagnation"
    return ""


def group_by_size(sizes, digits=2):
    """{rounded size: [faces]} so each size needs one FreeCAD mesh region."""
    groups = {}
    for face, size in sizes.items():
        key = round(size, digits - 1 - int(math.floor(math.log10(size)))) if size > 0 else size
        groups.setdefault(key, []).append(face)
    return {k: sorted(v, key=lambda f: int(f[4:]) if f[4:].isdigit() else f)
            for k, v in sorted(groups.items())}
