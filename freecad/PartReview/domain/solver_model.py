# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""How much memory and time CalculiX needs on THIS computer (pure, no Qt).

Peak memory and solve time of the direct solver grow as power laws of the node
count, y = a * n^b (b > 1: they grow faster than the mesh). The law is fitted in
log-log by least squares to measured runs: the reference PC of spike 8.0 until the
user measures their own computer with the benchmark. The relative error of the
law on its own samples is kept and used as a safety margin: a precise model
allows a mesh closer to the limit, an uncertain one keeps more margin.
"""

import math
from dataclasses import dataclass

MIN_ERROR = 0.15  # never trust a model more than +-15 %
TWO_POINT_ERROR = 0.30  # a law through 2 points has no residual to measure
REFERENCE_ERROR = 0.50  # reference PC model applied to an unmeasured computer


@dataclass(frozen=True)
class SolverSample:
    nodes: int
    seconds: float  # CalculiX wall time
    peak_mb: float  # CalculiX peak resident memory


@dataclass(frozen=True)
class PowerLaw:
    coeff: float
    exponent: float

    def __call__(self, nodes: float) -> float:
        return self.coeff * nodes ** self.exponent if nodes > 0 else 0.0

    def inverse(self, value: float) -> int:
        return int((value / self.coeff) ** (1.0 / self.exponent)) if value > 0 else 0


def fit_power_law(points) -> PowerLaw:
    """Least squares on (log n, log y); needs two different node counts."""
    xs = [math.log(n) for n, _ in points]
    ys = [math.log(y) for _, y in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        raise ValueError("need samples with different node counts")
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return PowerLaw(math.exp(my - b * mx), b)


@dataclass(frozen=True)
class SolverModel:
    memory: PowerLaw  # MB
    time: PowerLaw  # s
    error: float  # relative uncertainty used as safety margin
    samples: tuple = ()
    measured: bool = False  # True: measured on this part on this computer
    time_known: bool = True  # False: no measurement of THIS computer's speed yet
    memory_low: PowerLaw | None = None  # optimistic bound while not measured

    def memory_mb(self, nodes: int) -> float:
        return self.memory(nodes)

    def seconds(self, nodes: int) -> float:
        return self.time(nodes)

    def safe_max_nodes(self, memory_mb: float | None = None,
                       seconds: float | None = None) -> int:
        """Largest mesh whose estimate, plus the error margin, stays within the limits."""
        limits = []
        if memory_mb is not None:
            limits.append(self.memory.inverse(memory_mb / (1.0 + self.error)))
        if seconds is not None:
            limits.append(self.time.inverse(seconds / (1.0 + self.error)))
        return min(limits) if limits else 0


def fit_model(samples, measured=True) -> SolverModel:
    samples = tuple(sorted(samples, key=lambda s: s.nodes))
    memory = fit_power_law([(s.nodes, s.peak_mb) for s in samples])
    time = fit_power_law([(s.nodes, max(s.seconds, 0.05)) for s in samples])
    if len(samples) < 3:
        error = TWO_POINT_ERROR
    else:
        residuals = [abs(memory(s.nodes) / s.peak_mb - 1.0) for s in samples]
        residuals += [abs(time(s.nodes) / max(s.seconds, 0.05) - 1.0) for s in samples]
        error = max(MIN_ERROR, max(residuals))
    return SolverModel(memory, time, error, samples, measured)


# Solver memory is a property of the mesh and the solver, not of the computer: the
# same matrix needs the same bytes everywhere. It depends a lot on the part's shape,
# so before measuring it is a band between two measured shapes (spooles, tet10):
#   thin-walled part (owner's, spike 8.0): 56 445 -> 1 029 MB, 95 129 -> 2 082 MB
#   compact block (benchmark):             32 075 -> 1 284 MB, 53 626 -> 2 570 MB
# Solve TIME depends on the computer: it is never predicted from another machine.
THIN_SAMPLES = (SolverSample(56445, 10.5, 1029.0), SolverSample(95129, 27.6, 2082.0))
COMPACT_SAMPLES = (SolverSample(32075, 14.8, 1284.0), SolverSample(53626, 47.6, 2570.0))
MEMORY_LOW = fit_power_law([(s.nodes, s.peak_mb) for s in THIN_SAMPLES])
MEMORY_HIGH = fit_power_law([(s.nodes, s.peak_mb) for s in COMPACT_SAMPLES])
# Time law of the reference PC: only its exponent (how time grows with the mesh) is
# reused; its scale is replaced by this computer's measurements.
REFERENCE_TIME = fit_power_law([(s.nodes, s.seconds) for s in THIN_SAMPLES])


def prior_model(machine_time: "PowerLaw | None" = None) -> "SolverModel":
    """Model before any CalculiX trial on this part: memory on the safe (compact) side,
    time from this computer's earlier measurements, or unknown."""
    return SolverModel(MEMORY_HIGH, machine_time or REFERENCE_TIME, REFERENCE_ERROR, (),
                       measured=False, time_known=machine_time is not None,
                       memory_low=MEMORY_LOW)


REFERENCE = prior_model()  # kept for older callers: memory band, time unknown


def speed_factor(samples) -> float:
    """This computer's solve time relative to the reference PC (1 = same speed,
    2 = twice as slow), from CalculiX trials: median ratio at the same node count."""
    ratios = sorted(max(s.seconds, 0.05) / REFERENCE_TIME(s.nodes) for s in samples)
    if not ratios:
        return 1.0
    mid = len(ratios) // 2
    return ratios[mid] if len(ratios) % 2 else 0.5 * (ratios[mid - 1] + ratios[mid])


def format_duration(seconds: float) -> str:
    """'45 s', '3 min 20 s', '1 h 05 min' (language-neutral units)."""
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return "%d s" % seconds
    if seconds < 3600:
        return "%d min %02d s" % divmod(seconds, 60)
    hours, rest = divmod(seconds, 3600)
    return "%d h %02d min" % (hours, rest // 60)
