# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Planning the 'best mesh for this computer' (pure, no Qt).

1. Gmsh trials give the real node count of each option (cheap: seconds).
2. CalculiX probes on the smaller trial meshes of THIS part on THIS computer give
   memory and time; a power law fitted to them predicts the bigger meshes.
3. An objective (fits in memory, or solves within 1 / 5 / 10 minutes) becomes a
   target node count, with the model error as safety margin, and the element
   size for it comes from the node-vs-size law of the Gmsh trials.
"""

from dataclasses import dataclass
from enum import Enum

from .solver_model import (MEMORY_HIGH, MEMORY_LOW, REFERENCE_TIME, PowerLaw, SolverModel,
                           fit_model, fit_power_law, prior_model, speed_factor)

PROBE_MIN_NODES = 15000  # below this the solver's fixed memory dominates the fit
PROBE_MAX_SECONDS = 60.0  # a probe may be predicted up to 60 s (with margin)
PROBE_MEMORY_SHARE = 0.6  # ... and up to 60 % of the free memory (watchdog kills at 65 %)
GMSH_MAX_NODES = 3_000_000  # never ask Gmsh for more (it would take minutes and GBs)
# One trial + theoretical exponents. Checked on every measured run of the project:
# the 4/3 law through the SMALLEST trial predicted the larger runs 1-23 % too low
# (never too high), so one trial needs a 25 % margin; the largest trial is used.
ONE_POINT_ERROR = 0.25


class Objective(Enum):
    MEMORY = "memory"  # finest mesh that fits in memory with margin
    MIN_1 = "min_1"
    MIN_5 = "min_5"
    MIN_10 = "min_10"


OBJECTIVE_SECONDS = {Objective.MEMORY: None, Objective.MIN_1: 60.0, Objective.MIN_5: 300.0,
                     Objective.MIN_10: 600.0}


def part_model(samples, machine_time: PowerLaw | None = None) -> SolverModel:
    """Solver law for this part on this computer from the probes made so far.

    No probe yet: memory band from two measured shapes (machine-independent) and the
    time this computer showed on earlier parts, if any (``machine_time``)."""
    measured = [s for s in samples if s.measured]  # a run too short to sample is no data
    useful = [s for s in measured if s.nodes >= PROBE_MIN_NODES]
    if len(useful) >= 2:
        return fit_model(useful)
    if measured:  # one point: theoretical exponents, coefficient through the largest
        s = max(measured, key=lambda x: x.nodes)
        model = fit_model([s])
        return SolverModel(model.memory, model.time, ONE_POINT_ERROR, tuple(measured), True)
    return prior_model(machine_time)


def machine_time_law(samples) -> PowerLaw:
    """This computer's time law: reference exponent, scale from its own trials."""
    k = speed_factor(samples)
    return PowerLaw(REFERENCE_TIME.coeff * k, REFERENCE_TIME.exponent)


PROBE_PLANNING_ERROR = 0.25  # planning margin for probes; the watchdog is the hard stop


def probe_allowed(model: SolverModel, nodes: int, free_mb: float) -> bool:
    """Memory is checked always (it does not depend on the computer); time only once
    this computer's speed is known; before that the watchdog's time limit protects."""
    margin = 1.0 + min(model.error, PROBE_PLANNING_ERROR)
    if model.memory_mb(nodes) * margin > PROBE_MEMORY_SHARE * free_mb:
        return False
    return not model.time_known or model.seconds(nodes) * margin <= PROBE_MAX_SECONDS


def target_nodes(model: SolverModel, free_mb: float, objective: Objective,
                 memory_share: float) -> int:
    return model.safe_max_nodes(memory_mb=memory_share * free_mb,
                                seconds=OBJECTIVE_SECONDS[objective])


def is_hopeless(model: SolverModel, nodes: float, free_mb: float, share: float) -> bool:
    """Clearly too big to solve here: even the optimistic memory exceeds ``share``x the
    free memory (used to skip Gmsh trials that cannot be useful)."""
    low = model.memory_low(nodes) if model.memory_low is not None else model.memory_mb(nodes)
    return low > share * free_mb


def binding_limit(model: SolverModel, free_mb: float, objective: Objective,
                  memory_share: float) -> str:
    """'memory' or 'time': which limit decides the target of an objective."""
    seconds = OBJECTIVE_SECONDS[objective]
    if seconds is None:
        return "memory"
    by_memory = model.safe_max_nodes(memory_mb=memory_share * free_mb)
    by_time = model.safe_max_nodes(seconds=seconds)
    return "time" if by_time < by_memory else "memory"


PROBE_TARGETS = (20000, 35000, 55000)  # nodes of the CalculiX trial meshes
PROBE_TET_FACTOR = 2.0  # real/formula nodes without curvature sizing (spike 8.0: 1.9)


def probe_size(volume: float, target_nodes: int) -> float:
    """Element size of a CalculiX trial mesh (no curvature refinement) for about
    ``target_nodes`` nodes: trial meshes are small on purpose, so the first
    measurement fits on any computer, whatever the part's tiny details."""
    from .mesh_sizing import NODES_PER_TET, TETS_PER_UNIT_VOLUME
    return (volume * TETS_PER_UNIT_VOLUME * NODES_PER_TET * PROBE_TET_FACTOR
            / target_nodes) ** (1.0 / 3.0)


def nodes_law(trials) -> PowerLaw:
    """nodes = c * size^p (p ~ -3) from (size, nodes) Gmsh trials."""
    return fit_power_law([(size, nodes) for size, nodes in trials])


def size_for_nodes(law: PowerLaw, nodes: int) -> float:
    return (nodes / law.coeff) ** (1.0 / law.exponent)


@dataclass(frozen=True)
class ProgressEstimate:
    done: int
    total: int
    remaining_s: float


def remaining_seconds(gmsh_s_per_node: float, pending_gmsh_nodes, model: SolverModel,
                      pending_probe_nodes) -> float:
    """Rough time left: Gmsh scales ~linearly with nodes, probes follow the solver law."""
    return (gmsh_s_per_node * sum(pending_gmsh_nodes)
            + sum(model.seconds(n) + gmsh_s_per_node * n for n in pending_probe_nodes))


def classify(model: SolverModel, nodes: int, free_mb: float, measured_mb=None):
    """Fit status of a mesh: a measured peak is used as is; a predicted one with the
    model error added (the safe side)."""
    from .mesh_budget import FITS_FRACTION, TIGHT_FRACTION, BudgetStatus
    memory = measured_mb if measured_mb is not None else model.memory_mb(nodes) * (1 + model.error)
    if memory <= FITS_FRACTION * free_mb:
        return BudgetStatus.FITS
    if memory <= TIGHT_FRACTION * free_mb:
        return BudgetStatus.TIGHT
    return BudgetStatus.TOO_BIG


# FreeCAD around CalculiX: write the input (constraint node search) and load the
# result. Measured on the reference PC (57 299 nodes): 2.9 s + 6.8 s. On another
# computer it is scaled by that computer's measured speed factor.
FREECAD_OVERHEAD_S_PER_NODE = (2.9 + 6.8) / 57299.0
RECOMMEND_FINE_SECONDS = 120.0  # recommend "fine" when it fits and solves within 2 min


def total_seconds(model: SolverModel, nodes: int, solver_seconds: float | None = None,
                  speed: float = 1.0) -> float:
    """What the user waits for after clicking solve in FreeCAD (order of magnitude);
    ``speed``: this computer's speed factor (FreeCAD's own part scales with it)."""
    solver = model.seconds(nodes) if solver_seconds is None else solver_seconds
    return solver + FREECAD_OVERHEAD_S_PER_NODE * speed * nodes


def recommend(statuses: dict, seconds: dict):
    """Recommended level from fit status and total time per tried level.

    Quadratic tetrahedra need about 2 elements across a wall for bending stresses
    (medium); one element (coarse) gave 24 % estimated error on the owner's part.
    Fine is preferred when it fits and solves quickly; coarse only when medium does
    not fit (the panel then warns that the error tends to be high).
    Returns (level, reason key).
    """
    from .mesh_budget import BudgetStatus
    from .mesh_sizing import MeshLevel
    fits = {lv for lv, st in statuses.items() if st is BudgetStatus.FITS}
    if MeshLevel.FINE in fits and seconds.get(MeshLevel.FINE, 1e9) <= RECOMMEND_FINE_SECONDS:
        return MeshLevel.FINE, "ma.recommend.fine"
    if MeshLevel.MEDIUM in fits:
        return MeshLevel.MEDIUM, "ma.recommend.medium"
    if MeshLevel.COARSE in fits:
        return MeshLevel.COARSE, "ma.recommend.coarse"
    return MeshLevel.VERY_COARSE, "ma.recommend.very_coarse"
