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

from .solver_model import REFERENCE, PowerLaw, SolverModel, fit_model, fit_power_law

PROBE_MIN_NODES = 15000  # below this the solver's fixed memory dominates the fit
PROBE_MAX_SECONDS = 60.0  # a probe may be predicted up to 60 s (with margin)
PROBE_MEMORY_SHARE = 0.5  # ... and up to 50 % of the free memory
GMSH_MAX_NODES = 3_000_000  # never ask Gmsh for more (it would take minutes and GBs)
ONE_POINT_ERROR = 0.4  # reference law rescaled through a single measured point


class Objective(Enum):
    MEMORY = "memory"  # finest mesh that fits in memory with margin
    MIN_1 = "min_1"
    MIN_5 = "min_5"
    MIN_10 = "min_10"


OBJECTIVE_SECONDS = {Objective.MEMORY: None, Objective.MIN_1: 60.0, Objective.MIN_5: 300.0,
                     Objective.MIN_10: 600.0}


def part_model(samples) -> SolverModel:
    """Solver law for this part on this computer from the probes made so far."""
    useful = [s for s in samples if s.nodes >= PROBE_MIN_NODES]
    if len(useful) >= 2:
        return fit_model(useful)
    if samples:  # one point: keep the reference exponents, rescale through the point
        s = max(samples, key=lambda x: x.nodes)
        memory = PowerLaw(s.peak_mb / s.nodes ** REFERENCE.memory.exponent,
                          REFERENCE.memory.exponent)
        time = PowerLaw(max(s.seconds, 0.05) / s.nodes ** REFERENCE.time.exponent,
                        REFERENCE.time.exponent)
        return SolverModel(memory, time, ONE_POINT_ERROR, tuple(samples), True)
    return REFERENCE


PROBE_PLANNING_ERROR = 0.25  # planning margin for probes; the watchdog is the hard stop


def probe_allowed(model: SolverModel, nodes: int, free_mb: float) -> bool:
    margin = 1.0 + min(model.error, PROBE_PLANNING_ERROR)
    return (model.seconds(nodes) * margin <= PROBE_MAX_SECONDS
            and model.memory_mb(nodes) * margin <= PROBE_MEMORY_SHARE * free_mb)


def target_nodes(model: SolverModel, free_mb: float, objective: Objective,
                 memory_share: float) -> int:
    return model.safe_max_nodes(memory_mb=memory_share * free_mb,
                                seconds=OBJECTIVE_SECONDS[objective])


def binding_limit(model: SolverModel, free_mb: float, objective: Objective,
                  memory_share: float) -> str:
    """'memory' or 'time': which limit decides the target of an objective."""
    seconds = OBJECTIVE_SECONDS[objective]
    if seconds is None:
        return "memory"
    by_memory = model.safe_max_nodes(memory_mb=memory_share * free_mb)
    by_time = model.safe_max_nodes(seconds=seconds)
    return "time" if by_time < by_memory else "memory"


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
