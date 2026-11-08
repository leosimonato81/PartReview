# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Memory budget for the solver, from data that exists BEFORE solving (pure, no Qt).

The CalculiX direct solver (spooles, FreeCAD's default) is what exhausts memory on
modest computers, not the mesher (spike 8.0, decision 007). Its peak memory grows
faster than the number of nodes. Calibration measured on the reference machine
(i5 9th gen, 8 GB, FreeCAD 1.1.4 Flatpak, 2nd-order tetrahedra, 8 threads):

    56 445 nodes -> 1 029 MB      95 129 nodes -> 2 082 MB
    183 059 nodes -> more than 4 500 MB (killed while swapping)

A power law through the two complete runs reproduces the third one (it predicts
about 5 GB). The estimate is an order of magnitude, not a guarantee: geometry,
element order and solver settings change the real value.
"""

import math
from dataclasses import dataclass
from enum import Enum

# (nodes, peak MB of the CalculiX process) measured in spike 8.0
CCX_CALIBRATION = ((56445, 1029.0), (95129, 2082.0))
CCX_LOWER_BOUND = (183059, 4500.0)  # killed above this: the real peak was higher

FITS_FRACTION = 0.60  # "fits": estimate up to 60 % of the memory free right now
TIGHT_FRACTION = 0.85  # "tight": up to 85 %; above that "does not fit"


def _fit(points):
    (n1, m1), (n2, m2) = points
    exponent = math.log(m2 / m1) / math.log(n2 / n1)
    return m1 / n1 ** exponent, exponent


_COEFF, _EXPONENT = _fit(CCX_CALIBRATION)


def solver_memory_mb(nodes: int) -> float:
    """Estimated peak memory (MB) of CalculiX for a mesh with ``nodes`` nodes."""
    if nodes <= 0:
        return 0.0
    return _COEFF * nodes ** _EXPONENT


def max_nodes_for(memory_mb: float) -> int:
    """Largest node count whose estimated solver memory stays within ``memory_mb``."""
    if memory_mb <= 0:
        return 0
    return int((memory_mb / _COEFF) ** (1.0 / _EXPONENT))


@dataclass(frozen=True)
class MachineProfile:
    total_mb: float
    available_mb: float  # free for new programs right now (Linux: MemAvailable)
    cores: int = 1
    estimated: bool = False  # True when the free memory could not be read exactly


class BudgetStatus(Enum):
    FITS = "fits"
    TIGHT = "tight"
    TOO_BIG = "too_big"


@dataclass(frozen=True)
class BudgetCheck:
    status: BudgetStatus
    nodes: int
    memory_mb: float  # estimated solver peak
    available_mb: float
    max_nodes_fits: int  # largest mesh that would still be "fits"

    @property
    def share(self) -> float:
        """Estimated memory as a fraction of the free memory."""
        return self.memory_mb / self.available_mb if self.available_mb > 0 else math.inf


def check_budget(nodes: int, machine: MachineProfile) -> BudgetCheck:
    memory = solver_memory_mb(nodes)
    free = machine.available_mb
    if memory <= FITS_FRACTION * free:
        status = BudgetStatus.FITS
    elif memory <= TIGHT_FRACTION * free:
        status = BudgetStatus.TIGHT
    else:
        status = BudgetStatus.TOO_BIG
    return BudgetCheck(status, nodes, memory, free, max_nodes_for(FITS_FRACTION * free))
