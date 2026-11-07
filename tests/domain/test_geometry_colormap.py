# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import math

import pytest

from freecad.PartReview.domain import colormap
from freecad.PartReview.domain import geometry as g
from freecad.PartReview.domain.models import Vec3


def test_vector_basics():
    a, b = Vec3(1, 0, 0), Vec3(0, 1, 0)
    assert g.cross(a, b) == Vec3(0, 0, 1)
    assert g.dot(a, b) == 0
    assert g.length(Vec3(3, 4, 0)) == 5
    assert g.angle_deg(a, b) == pytest.approx(90)
    with pytest.raises(ValueError):
        g.normalize(Vec3(0, 0, 0))


def test_fibonacci_sphere_unit_and_balanced():
    pts = g.fibonacci_sphere(100)
    assert len(pts) == 100
    assert all(abs(g.length(p) - 1) < 1e-9 for p in pts)
    assert abs(sum(p.z for p in pts)) < 1e-6  # as many up as down


@pytest.mark.parametrize("p, expected", [
    (Vec3(0.2, 0.2, 1.0), 1.0),        # above the face
    (Vec3(-1.0, 0.0, 0.0), 1.0),       # beyond vertex a
    (Vec3(0.5, -2.0, 0.0), 2.0),       # beyond edge ab
    (Vec3(1.0, 1.0, 0.0), math.sqrt(0.5)),  # beyond edge bc
])
def test_point_triangle_distance(p, expected):
    a, b, c = Vec3(0, 0, 0), Vec3(1, 0, 0), Vec3(0, 1, 0)
    assert g.point_triangle_distance(p, a, b, c) == pytest.approx(expected)


def test_unit_scalar_and_extremes_forced():
    assert colormap.to_unit_scalar(0.0, 0.0, 10.0) == -1.0
    assert colormap.to_unit_scalar(5.0, 0.0, 10.0) == 0.0
    assert colormap.to_unit_scalar(99.0, 0.0, 10.0) == 1.0
    assert colormap.to_unit_scalar(3.0, 3.0, 3.0) == 0.0
    s = colormap.scalars_for_freecad([2.0, 4.0, 6.0], 0.0, 10.0)
    assert min(s) == -1.0 and max(s) == 1.0


def test_color_at_matches_freecad_stops():
    assert colormap.color_at(0.0) == (0.0, 0.0, 1.0)
    assert colormap.color_at(0.5) == (0.0, 1.0, 0.0)
    assert colormap.color_at(1.0) == (1.0, 0.0, 0.0)
    assert colormap.color_at(0.875) == pytest.approx((1.0, 0.5, 0.0))


def test_tick_values():
    assert colormap.tick_values(0.0, 1.0, 5) == [0.0, 0.25, 0.5, 0.75, 1.0]
