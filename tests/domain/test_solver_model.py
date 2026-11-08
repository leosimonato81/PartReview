# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import pytest

from freecad.PartReview.domain.solver_model import (
    REFERENCE,
    SolverSample,
    fit_model,
    fit_power_law,
    format_duration,
)


def test_power_law_fit_is_exact_on_a_power_law():
    law = fit_power_law([(n, 3.0 * n ** 1.4) for n in (1e4, 3e4, 9e4)])
    assert law.exponent == pytest.approx(1.4) and law.coeff == pytest.approx(3.0)
    assert law.inverse(law(5e4)) == pytest.approx(5e4, abs=1)  # rounds down: safe side


def test_prior_memory_band_covers_both_measured_shapes():
    from freecad.PartReview.domain.solver_model import MEMORY_HIGH, MEMORY_LOW
    # theoretical exponent 4/3: the two measured points of each shape within 1 %
    assert MEMORY_LOW(56445) == pytest.approx(1029, rel=0.01)  # thin-walled part
    assert MEMORY_HIGH(53626) == pytest.approx(2570, rel=0.01)  # compact block
    assert MEMORY_LOW.exponent == MEMORY_HIGH.exponent == pytest.approx(4 / 3)
    assert MEMORY_LOW(183059) > 4500  # the run that froze the PC is too big anyway
    assert not REFERENCE.measured and not REFERENCE.time_known and REFERENCE.error == 0.5


def test_error_margin_comes_from_the_residuals():
    exact = [SolverSample(n, 1e-4 * n ** 1.8, 0.02 * n ** 1.35) for n in (1e4, 2e4, 4e4, 8e4)]
    assert fit_model(exact).error == pytest.approx(0.15)  # floor
    noisy = exact[:3] + [SolverSample(8e4, 1.6 * exact[3].seconds, exact[3].peak_mb)]
    assert fit_model(noisy).error > 0.15
    assert fit_model(exact[:2]).error == 0.30


def test_safe_limits_shrink_with_uncertainty():
    precise = fit_model([SolverSample(n, 1e-4 * n ** 1.8, 0.02 * n ** 1.35)
                         for n in (1e4, 2e4, 4e4, 8e4)])
    unsure = REFERENCE
    for model in (precise, unsure):
        n = model.safe_max_nodes(seconds=300)
        assert model.seconds(n) * (1 + model.error) <= 300.0 + 1e-6
    n_mem = precise.safe_max_nodes(memory_mb=2000)
    n_both = precise.safe_max_nodes(memory_mb=2000, seconds=1.0)
    assert n_both <= n_mem


def test_duration_text():
    assert format_duration(42) == "42 s"
    assert format_duration(200) == "3 min 20 s"
    assert format_duration(3900) == "1 h 05 min"


def test_unmeasured_runs_are_not_data():
    from freecad.PartReview.domain import mesh_plan as mp
    from freecad.PartReview.domain.solver_model import SolverSample, speed_factor
    tiny = SolverSample(1444, 0.8, 0.0)  # too fast for the memory watchdog
    assert not tiny.measured
    model = mp.part_model([tiny])  # must not crash: falls back to the prior band
    assert model.memory_mb(50000) > 0
    big = SolverSample(57000, 11.4, 2300.0)
    assert mp.part_model([tiny, big]).memory_mb(57000) == pytest.approx(2300.0, rel=1e-6)
    # start-up time of a tiny run must not make the computer look slow
    assert speed_factor([SolverSample(1444, 5.0, 50.0), big]) == speed_factor([big])
