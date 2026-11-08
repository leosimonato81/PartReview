# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import pytest

from freecad.PartReview.domain import camera_planner as cp
from freecad.PartReview.domain import geometry as g
from freecad.PartReview.domain.hotspots import Hotspot, HotspotKind
from freecad.PartReview.domain.models import FieldKind, Vec3

ORIGIN = Vec3(0.0, 0.0, 0.0)


def always_visible(point, direction):
    return True


def spot(kind=HotspotKind.STRESS_MAX, center=Vec3(0, 0, 1), normal=Vec3(0, 0, 1),
         radius=0.5, field=FieldKind.VON_MISES):
    return Hotspot(kind=kind, center=center, radius=radius, normal=normal,
                   sample_points=(center,), color_field=field)


def test_up_vector_is_perpendicular_and_prefers_z():
    up = cp.up_for(Vec3(1, 0, 0))
    assert up == pytest.approx(Vec3(0, 0, 1))
    up = cp.up_for(Vec3(0, 0, -1))  # looking down: use Y
    assert up == pytest.approx(Vec3(0, 1, 0))
    d = g.normalize(Vec3(1, -1, -1))
    assert g.dot(cp.up_for(d), d) == pytest.approx(0.0, abs=1e-12)


def test_frame_never_clips_the_model():
    cam = cp.frame(Vec3(0, 0, -1), Vec3(5, 0, 0), 2.0, ORIGIN, 10.0)
    reach = 10.0 + 5.0
    # every model point lies between near and far along the view direction
    for p in (Vec3(-10, 0, 0), Vec3(10, 0, 10), Vec3(0, 0, -10)):
        depth = g.dot(g.sub(p, cam.position), cam.direction)
        assert cam.near <= depth <= cam.far
    assert cam.height == 4.0
    assert cam.distance == 2 * reach


def test_target_view_looks_at_the_surface_slightly_oblique():
    view = cp.plan_target_view(spot(), ORIGIN, 10.0, always_visible)
    f = cp.facing(view.camera.direction, Vec3(0, 0, 1))
    assert 0.65 <= f <= 0.95  # near the preferred ~37 degrees, not edge-on, not dead-on
    assert view.targets[0].kind is HotspotKind.STRESS_MAX


def test_facing_score_peaks_at_preferred_angle():
    n = Vec3(0, 0, 1)
    dead_on = cp.facing_score(Vec3(0, 0, -1), n)
    edge_on = cp.facing_score(Vec3(1, 0, 0), n)
    import math
    a = math.acos(cp.PREFERRED_FACING)
    best = cp.facing_score(Vec3(math.sin(a), 0, -math.cos(a)), n)
    assert best == pytest.approx(1.0)
    assert best > dead_on > edge_on == 0.0


def test_faces_are_framed_tighter_than_spots():
    face = spot(kind=HotspotKind.SUPPORT, radius=4.0)
    point = spot(kind=HotspotKind.STRESS_MAX, radius=4.0)
    assert cp.frame_half_height(face, 10.0) < cp.frame_half_height(point, 10.0)


def test_target_view_avoids_occluded_directions():
    # the straight-on direction is blocked: something must be chosen that sees it
    def blocked_from_top(point, direction):
        return g.angle_deg(direction, Vec3(0, 0, -1)) > 20

    view = cp.plan_target_view(spot(), ORIGIN, 10.0, blocked_from_top)
    assert blocked_from_top(Vec3(0, 0, 1), view.camera.direction)
    assert cp.facing(view.camera.direction, Vec3(0, 0, 1)) > 0.5


def test_projection_center_and_axes():
    cam = cp.frame(Vec3(0, 1, 0), ORIGIN, 5.0, ORIGIN, 10.0)  # front view, height 10
    assert cp.project(cam, ORIGIN, 800, 600) == pytest.approx((400, 300))
    u, v = cp.project(cam, Vec3(0, 0, 5), 800, 600)  # top edge of the image
    assert (u, v) == pytest.approx((400, 0))
    u, v = cp.project(cam, Vec3(5, 0, 0), 800, 600)  # +X is to the right
    assert u == pytest.approx(400 + 300) and v == pytest.approx(300)
    with pytest.raises(ValueError):
        cp.project(cam, ORIGIN, 600, 800)


def test_overview_prefers_direction_that_sees_targets():
    a = spot(center=Vec3(5, 5, 5))

    def only_from_positive_corner(point, direction):
        return direction.x < 0 and direction.y < 0 and direction.z < 0

    view = cp.plan_overview(FieldKind.VON_MISES, [a], ORIGIN, 10.0, only_from_positive_corner)
    assert view.is_overview
    assert view.camera.direction.x < 0 and view.camera.direction.z < 0
    assert view.targets == (a,)


def test_select_views_merges_neighbors_and_limits_count():
    near1 = cp.plan_target_view(spot(center=Vec3(0, 0, 1)), ORIGIN, 10.0, always_visible)
    near2 = cp.plan_target_view(spot(kind=HotspotKind.STRESS, center=Vec3(0.3, 0, 1)),
                                ORIGIN, 10.0, always_visible)
    other_field = cp.plan_target_view(
        spot(kind=HotspotKind.DISPLACEMENT_MAX, field=FieldKind.DISPLACEMENT),
        ORIGIN, 10.0, always_visible)
    kept = cp.select_views([near2, other_field, near1])
    assert len(kept) == 2
    assert kept[0].targets[0].kind is HotspotKind.STRESS_MAX  # priority order
    assert len(kept[0].targets) == 2  # near2 merged into near1
    many = [cp.plan_target_view(spot(center=Vec3(0, 0, 1), normal=n), ORIGIN, 10.0,
                                always_visible) for n in cp.AXES]
    assert len(cp.select_views(many, max_views=4)) == 4


def test_merged_views_do_not_repeat_a_target():
    # An overview that already shows a load, plus the load's own close-up: merging
    # them must not list the load twice (it drew two identical balloons).
    load = spot(kind=HotspotKind.LOAD, center=Vec3(0, 0, 1))
    stress = spot(center=Vec3(0.2, 0, 1))
    first = cp.plan_target_view(stress, ORIGIN, 10.0, always_visible)
    first = cp.PlannedView(first.camera, first.color_field, (stress, load))
    second = cp.PlannedView(first.camera, first.color_field, (load,))
    for view in cp.select_views([first, second]):
        assert len(view.targets) == len(set(view.targets))
