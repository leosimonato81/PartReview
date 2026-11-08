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
    measured: bool = False  # True: measured on this computer (benchmark)

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


# Spike 8.0 on the reference PC (i5 9th gen, 8 GB, 8 threads, spooles, tet10).
REFERENCE_SAMPLES = (SolverSample(56445, 10.5, 1029.0), SolverSample(95129, 27.6, 2082.0))
_reference = fit_model(REFERENCE_SAMPLES, measured=False)
REFERENCE = SolverModel(_reference.memory, _reference.time, REFERENCE_ERROR,
                        REFERENCE_SAMPLES, measured=False)


def format_duration(seconds: float) -> str:
    """'45 s', '3 min 20 s', '1 h 05 min' (language-neutral units)."""
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return "%d s" % seconds
    if seconds < 3600:
        return "%d min %02d s" % divmod(seconds, 60)
    hours, rest = divmod(seconds, 3600)
    return "%d h %02d min" % (hours, rest // 60)
