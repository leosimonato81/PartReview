# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""The report must not mislead: the worst point is never hidden to show lesser ones,
figures read overview -> close-ups per quantity, and the stress away from
supports/loads is reported next to a possibly singular maximum."""

from freecad.PartReview.domain import camera_planner as cp
from freecad.PartReview.domain.hotspots import Hotspot, HotspotKind, regular_stress_hotspot
from freecad.PartReview.domain.models import (Constraint, ConstraintKind, FieldKind,
                                              ResultField, Vec3)
from freecad.PartReview.domain.surface import build_surface

from test_surface_hotspots import bar_mesh, square

ORIGIN = Vec3(0.0, 0.0, 0.0)


def spot(kind, center, field=FieldKind.VON_MISES):
    return Hotspot(kind=kind, center=center, radius=0.1, normal=None,
                   sample_points=(center,), color_field=field)


def test_overview_never_hides_the_maximum_to_show_two_lesser_points():
    top = spot(HotspotKind.STRESS_MAX, Vec3(0, 0, 1))
    low1, low2 = spot(HotspotKind.STRESS, Vec3(0, 0, -1)), spot(HotspotKind.STRESS, Vec3(0, 0, -2))

    def visible(p, d):  # the maximum is seen only from above, the others only from below
        return (p.z > 0 and d.z < 0) or (p.z < 0 and d.z > 0)

    view = cp.plan_overview(FieldKind.VON_MISES, [top, low1, low2], ORIGIN, 3.0, visible)
    assert top in view.targets and low1 not in view.targets


def test_reading_order_is_overview_then_its_close_ups_per_quantity():
    s1, s2 = spot(HotspotKind.STRESS_MAX, ORIGIN), spot(HotspotKind.STRESS, Vec3(1, 0, 0))
    d1 = spot(HotspotKind.DISPLACEMENT_MAX, Vec3(2, 0, 0), FieldKind.DISPLACEMENT)
    cam = cp.frame(Vec3(0, 0, -1), ORIGIN, 1.0, ORIGIN, 3.0)
    views = [cp.PlannedView(cam, FieldKind.VON_MISES, (s1, s2), is_overview=True),
             cp.PlannedView(cam, FieldKind.DISPLACEMENT, (d1,), is_overview=True),
             cp.PlannedView(cam, FieldKind.DISPLACEMENT, (d1,)),
             cp.PlannedView(cam, FieldKind.VON_MISES, (s2,)),
             cp.PlannedView(cam, FieldKind.VON_MISES, (s1,))]
    ordered = cp.reading_order(views, [s1, d1, s2])
    assert ordered == [views[0], views[4], views[3], views[1], views[2]]


def test_stress_away_from_supports_is_found_when_the_maximum_sits_on_one():
    mesh, elements = bar_mesh(6)
    surface = build_surface(elements, mesh.node_positions)
    ids = tuple(mesh.node_positions)
    # highest at the clamped end x = 0, a lesser peak at x = 4
    values = tuple(10.0 - mesh.node_positions[n].x if mesh.node_positions[n].x < 2
                   else (5.0 if mesh.node_positions[n].x == 4 else 1.0) for n in ids)
    stress = ResultField(FieldKind.VON_MISES, "MPa", ids, values)
    fixed = Constraint(ConstraintKind.FIXED, "Engaste", geometry=square(0.0))
    spot_ = regular_stress_hotspot(stress, mesh, surface, [fixed], exclusion=2.5)
    assert spot_ is not None and spot_.kind is HotspotKind.STRESS_REGULAR
    assert spot_.center.x == 4.0 and spot_.peak_value.value == 5.0
    # maximum already far from every support: nothing to add
    far = Constraint(ConstraintKind.FIXED, "Longe", geometry=square(6.0))
    assert regular_stress_hotspot(stress, mesh, surface, [far], exclusion=2.5) is None
