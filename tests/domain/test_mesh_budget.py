# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import pytest

from freecad.PartReview.domain.mesh_budget import (
    CCX_CALIBRATION,
    CCX_LOWER_BOUND,
    BudgetStatus,
    MachineProfile,
    check_budget,
    max_nodes_for,
    solver_memory_mb,
)

OWNER_PC = MachineProfile(total_mb=7274, available_mb=4170, cores=8)  # spike 8.0


def test_estimate_reproduces_the_calibration_runs():
    for nodes, memory in CCX_CALIBRATION:
        assert solver_memory_mb(nodes) == pytest.approx(memory, rel=1e-9)


def test_estimate_agrees_with_the_run_that_was_killed():
    nodes, at_least = CCX_LOWER_BOUND
    assert solver_memory_mb(nodes) > at_least


def test_memory_grows_faster_than_the_number_of_nodes():
    assert solver_memory_mb(200000) / solver_memory_mb(100000) > 2.0
    assert solver_memory_mb(0) == 0.0


def test_max_nodes_is_the_inverse():
    for memory in (500.0, 2000.0, 8000.0):
        n = max_nodes_for(memory)
        assert solver_memory_mb(n) <= memory < solver_memory_mb(n + 1000)


def test_owner_cases_on_the_reference_pc():
    assert check_budget(56445, OWNER_PC).status is BudgetStatus.FITS  # ran fine
    assert check_budget(95129, OWNER_PC).status is BudgetStatus.FITS  # ran fine (2.1 GB)
    froze = check_budget(183059, OWNER_PC)  # froze the PC
    assert froze.status is BudgetStatus.TOO_BIG
    assert froze.share > 1.0
    assert 95129 < froze.max_nodes_fits < 183059


def test_tight_band_between_fits_and_too_big():
    machine = MachineProfile(total_mb=8000, available_mb=1000)
    n_fits, n_tight = max_nodes_for(600), max_nodes_for(850)
    assert check_budget(n_fits, machine).status is BudgetStatus.FITS
    assert check_budget((n_fits + n_tight) // 2, machine).status is BudgetStatus.TIGHT
    assert check_budget(n_tight + 5000, machine).status is BudgetStatus.TOO_BIG


def test_message_for_the_mesh_that_froze_the_owner_pc():
    from freecad.PartReview.domain.i18n import Translator
    from freecad.PartReview.domain.mesh_budget import budget_message
    text = budget_message(check_budget(183059, OWNER_PC), OWNER_PC, Translator("pt_BR", strict=True))
    assert "Não deve caber" in text and "183 059 nós" in text
    assert "109 000 nós" in text and "4,07 GB" in text  # free memory, 2 decimals
    for lang in ("pt_BR", "en"):
        for status in BudgetStatus:
            check = check_budget({"fits": 1000, "tight": 120000, "too_big": 500000}[status.value],
                                 OWNER_PC)
            assert check.status is status
            budget_message(check, MachineProfile(8000, 4170, estimated=True),
                           Translator(lang, strict=True))


def test_small_memory_is_shown_in_megabytes():
    from freecad.PartReview.domain.i18n import Translator
    from freecad.PartReview.domain.mesh_budget import budget_message
    text = budget_message(check_budget(5362, OWNER_PC), OWNER_PC, Translator("en", strict=True))
    assert "~43 MB" in text and "4.07 GB" in text
