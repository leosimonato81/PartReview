# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import math

import pytest

from freecad.PartReview.domain.adaptive import (
    MAX_SHRINK, Pass, element_ratios, face_sizes, group_by_size, new_size, stop_reason)


def test_uniform_error_at_target_needs_no_refinement():
    # 4 elements, energy 96, error 4 -> global eta = sqrt(4/100) = 20 %
    ratios = element_ratios([1.0, 1.0, 1.0, 1.0], 96.0, 0.20)
    assert ratios == pytest.approx([1.0] * 4)
    assert all(new_size(2.0, r) == 2.0 for r in ratios)


def test_concentrated_error_refines_only_there():
    ratios = element_ratios([3.7, 0.1, 0.1, 0.1], 96.0, 0.20)
    assert ratios[0] > 1 and all(r < 1 for r in ratios[1:])
    # h_new = h * xi^(-1/2) for quadratic elements
    assert new_size(2.0, ratios[0]) == pytest.approx(2.0 / math.sqrt(ratios[0]))


def test_refinement_is_limited_per_pass():
    assert MAX_SHRINK == 0.5
    assert new_size(2.0, 1000.0) == pytest.approx(1.0)


def test_face_sizes_take_the_smallest_request_and_skip_singular_faces():
    faces = [("Face1",), ("Face1", "Face2"), ("Face3",), (), ("Face1",)]
    sizes = [2.0, 2.0, 2.0, 2.0, 2.0]
    ratios = [4.0, 1.5, 9.0, 9.0, 1.2]  # element 4 is inside (no face)
    out = face_sizes(faces, sizes, ratios, {"Face1": 2.0, "Face2": 2.0, "Face3": 2.0},
                     excluded={"Face3"})
    # Face1: requests 1.0, 1.63, 1.83 -> median 1.63 (not the worst one)
    assert out["Face1"] == pytest.approx(2.0 / math.sqrt(1.5))
    assert out["Face2"] == pytest.approx(2.0 / math.sqrt(1.5))
    assert "Face3" not in out  # singular: left alone


def test_no_change_when_the_face_is_already_that_fine():
    out = face_sizes([("Face1",)], [2.0], [4.0], {"Face1": 0.98})
    assert out == {}


def test_stop_reasons():
    p = lambda err: Pass(50000, err, 10, 8, 0.1, 30, 900)
    assert stop_reason([p(0.04)], 0.05) == "target"
    assert stop_reason([p(0.20), p(0.15)], 0.05) == ""
    assert stop_reason([p(0.20), p(0.19)], 0.05) == "stagnation"  # singularity pattern
    assert stop_reason([p(0.5 - 0.05 * i) for i in range(6)], 0.05) == "passes"


def test_group_by_size():
    groups = group_by_size({"Face10": 0.512, "Face2": 0.508, "Face3": 1.04})
    assert groups == {0.51: ["Face2", "Face10"], 1.0: ["Face3"]}
