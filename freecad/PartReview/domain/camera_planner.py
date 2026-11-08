# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Choose camera views that show each point of interest (decision 001).

Pure math. Visibility is injected as ``is_visible(point, view_direction)`` so
this module can be tested without FreeCAD; the adapter supplies a ray test
against the mesh surface.
"""

import math
from dataclasses import dataclass, replace
from typing import Callable

from . import geometry as g
from .hotspots import Hotspot, HotspotKind
from .models import FieldKind, Vec3

VisibilityFn = Callable[[Vec3, Vec3], bool]

WORLD_Z = Vec3(0.0, 0.0, 1.0)
WORLD_Y = Vec3(0.0, 1.0, 0.0)

AXES = (Vec3(1, 0, 0), Vec3(-1, 0, 0), Vec3(0, 1, 0), Vec3(0, -1, 0), Vec3(0, 0, 1),
        Vec3(0, 0, -1))
ISO = tuple(g.normalize(Vec3(x, y, z)) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1))


@dataclass(frozen=True)
class CameraSpec:
    """Orthographic camera. ``direction`` is where the camera looks."""

    direction: Vec3
    up: Vec3
    center: Vec3  # world point at the image center
    height: float  # visible world height of the image
    distance: float  # camera position = center - direction * distance
    near: float
    far: float

    @property
    def position(self) -> Vec3:
        return g.sub(self.center, g.scale(self.direction, self.distance))

    @property
    def right(self) -> Vec3:
        return g.normalize(g.cross(self.direction, self.up))


@dataclass(frozen=True)
class PlannedView:
    camera: CameraSpec
    color_field: FieldKind | None  # None: supports and loads view (no result colors)
    targets: tuple[Hotspot, ...]  # hotspots shown (marked) in this view
    is_overview: bool = False
    score: float = 0.0
    # Per target, the leader points visible in this view (filled after planning).
    # Empty tuple of tuples: not computed, every leader point is drawn.
    leaders: tuple = ()
    # Deformed-shape view: displacements drawn multiplied by this (0 = undeformed).
    deformation: float = 0.0

    @property
    def priority(self) -> int:
        return 0 if self.is_overview else min(t.priority for t in self.targets)


def up_for(direction: Vec3) -> Vec3:
    """World Z as 'up', unless looking almost straight up/down (then world Y)."""
    d = g.normalize(direction)
    up = WORLD_Y if abs(d.z) > 0.9 else WORLD_Z
    return g.normalize(g.sub(up, g.scale(d, g.dot(up, d))))


def frame(direction: Vec3, center: Vec3, half_height: float,
          model_center: Vec3, model_radius: float) -> CameraSpec:
    """Camera looking along ``direction`` at ``center``, never clipping the model."""
    d = g.normalize(direction)
    reach = model_radius + g.distance(center, model_center)  # farthest model point
    return CameraSpec(direction=d, up=up_for(d), center=center, height=2.0 * half_height,
                      distance=2.0 * reach, near=0.95 * reach, far=3.05 * reach)


def candidate_directions(normal: Vec3 | None, count: int = 48) -> list[Vec3]:
    dirs = list(g.fibonacci_sphere(count)) + list(AXES) + list(ISO)
    if normal is not None:
        dirs.append(g.scale(normal, -1.0))  # look straight at the surface
    return dirs


def facing(direction: Vec3, normal: Vec3 | None) -> float:
    """1 when the camera looks straight at the surface, 0 when edge-on or behind."""
    if normal is None:
        return 0.5
    return max(0.0, -g.dot(g.normalize(direction), normal))


# Looking dead-on at a flat face makes the picture look 2D; a slightly oblique
# view (facing 0.8, about 37 degrees off the normal) keeps the 3D context.
PREFERRED_FACING = 0.8


def facing_score(direction: Vec3, normal: Vec3 | None) -> float:
    """1 at the preferred oblique angle, lower when more edge-on or more dead-on."""
    f = facing(direction, normal)
    if f <= PREFERRED_FACING:
        return f / PREFERRED_FACING
    return 1.0 - 0.5 * (f - PREFERRED_FACING) / (1.0 - PREFERRED_FACING)


def frame_half_height(target: Hotspot, model_radius: float) -> float:
    """Close-ups of small spots show 3x their size; faces (supports/loads) fit snugly."""
    factor = 1.3 if target.kind in (HotspotKind.SUPPORT, HotspotKind.LOAD) else 3.0
    return max(factor * target.radius, 0.2 * model_radius)


def visible_fraction(points, direction: Vec3, is_visible: VisibilityFn) -> float:
    points = list(points)
    if not points:
        return 0.0
    return sum(1 for p in points if is_visible(p, direction)) / len(points)


def plan_target_view(target: Hotspot, model_center: Vec3, model_radius: float,
                     is_visible: VisibilityFn, shortlist: int = 16) -> PlannedView:
    """Best close-up view of one hotspot: visible, seen at a readable angle."""
    dirs = sorted(candidate_directions(target.normal),
                  key=lambda d: facing_score(d, target.normal), reverse=True)[:shortlist]
    best_dir, best_score = dirs[0], -1.0
    for d in dirs:
        score = (0.65 * visible_fraction(target.sample_points, d, is_visible)
                 + 0.35 * facing_score(d, target.normal))
        if score > best_score:
            best_dir, best_score = d, score
    camera = frame(best_dir, target.center, frame_half_height(target, model_radius),
                   model_center, model_radius)
    return PlannedView(camera, target.color_field, (target,), score=best_score)


OVERVIEW_DIRECTIONS = 48


def plan_overview(color_field: FieldKind, targets, model_center: Vec3, model_radius: float,
                  is_visible: VisibilityFn) -> PlannedView:
    """Whole-model isometric view that shows the most important targets first.

    ``targets`` come in report order (most important first). Target i weighs
    2**-i, so showing a point always beats showing all less important ones
    together: the overview never hides the maximum to show two lesser peaks.
    """
    targets = [t for t in targets if t.color_field is color_field]

    tie = 0.5 ** (len(targets) + 1)  # below any target's weight: only breaks ties

    def score(d):
        seen = sum(0.5 ** i for i, t in enumerate(targets) if is_visible(t.center, d))
        return seen + (tie if d in ISO else 0.0) + (0.5 * tie if d.z < 0 else 0.0)

    # Isometric views first (classic overview), then evenly spread directions,
    # used only when they show more of the important points.
    best = max(list(ISO) + list(g.fibonacci_sphere(OVERVIEW_DIRECTIONS)), key=score)
    camera = frame(best, model_center, 1.05 * model_radius, model_center, model_radius)
    shown = tuple(t for t in targets if is_visible(t.center, best))
    return PlannedView(camera, color_field, shown, is_overview=True, score=score(best))


DEFORMED_SHARE = 0.08  # largest drawn displacement = 8 % of the model radius


def deformation_scale(max_displacement: float, model_radius: float) -> float:
    """Magnification of the deformed shape: the largest displacement is drawn at
    about ``DEFORMED_SHARE`` of the model radius, rounded down to 1, 2 or 5 x 10^k
    so the caption reads well. Never below 1: a part that already deforms a lot
    (e.g. a flexible polymer) is drawn at true scale.
    """
    if max_displacement <= 0 or model_radius <= 0:
        return 1.0
    raw = DEFORMED_SHARE * model_radius / max_displacement
    if raw <= 1.0:
        return 1.0
    power = 10.0 ** math.floor(math.log10(raw))
    for step in (5.0, 2.0, 1.0):
        if step * power <= raw:
            return step * power
    return power


def drop_redundant_closeups(views) -> list[PlannedView]:
    """Displacement varies smoothly: when its overview already shows the maximum,
    a close-up of it adds nothing and only takes a figure from a stress point."""
    shown = {t for v in views if v.is_overview and v.color_field is FieldKind.DISPLACEMENT
             for t in v.targets}
    return [v for v in views if v.is_overview or v.color_field is not FieldKind.DISPLACEMENT
            or not all(t in shown for t in v.targets)]


FIELD_ORDER = (FieldKind.VON_MISES, FieldKind.DISPLACEMENT, FieldKind.ESTIMATED_ERROR)


def reading_order(views, ranking) -> list[PlannedView]:
    """Overview of a quantity, then its close-ups (by point number), then the next
    quantity: the reader goes from the whole part to the details of one result.

    ``ranking`` is the hotspot list in report order (its index is the number - 1).
    """
    rank = {h: i for i, h in enumerate(ranking)}

    def key(v):
        field = FIELD_ORDER.index(v.color_field) if v.color_field in FIELD_ORDER else 99
        first = min((rank.get(t, len(rank)) for t in v.targets), default=len(rank))
        return (field, not v.is_overview, first)

    return sorted(views, key=key)


BOUNDARY_KINDS = (HotspotKind.SUPPORT, HotspotKind.LOAD)


def plan_boundary_views(targets, model_center: Vec3, model_radius: float,
                        is_visible: VisibilityFn, max_views: int = 2) -> list[PlannedView]:
    """Whole-model views of the supports and loads (``color_field`` None: no result).

    The first view shows as many supports/loads as possible (one visible anchor
    is enough to point at it); a further view is added only for the ones still
    hidden, up to ``max_views``. Isometric directions are preferred because they
    keep the 3D context; the axes are a fallback (e.g. faces inside a slot).
    """
    targets = [t for t in targets if t.kind in BOUNDARY_KINDS]
    if not targets or max_views < 1:
        return []
    directions = list(ISO) + list(AXES)

    def seen(t, d):
        return any(is_visible(p, d) for p in t.anchors or (t.center,))

    def score(d, wanted):
        shown = sum(1 for t in wanted if seen(t, d))
        anchors = sum(1 for t in wanted for p in t.anchors or (t.center,) if is_visible(p, d))
        bonus = (0.3 if d in ISO else 0.0) + (0.2 if d.z < 0 else 0.0)  # iso, from above
        return 10.0 * shown + 0.1 * anchors + bonus

    views, missing = [], list(targets)
    while missing and len(views) < max_views:  # ends: max_views bounds it
        best = max(directions, key=lambda d: score(d, missing))
        shown = tuple(t for t in targets if seen(t, best))
        if not any(t in shown for t in missing):
            break  # nothing more can be shown from outside
        camera = frame(best, model_center, 1.05 * model_radius, model_center, model_radius)
        views.append(PlannedView(camera, None, shown, is_overview=True,
                                 score=score(best, targets)))
        missing = [t for t in missing if t not in shown]
    return views


def project(camera: CameraSpec, point: Vec3, width: int, height: int) -> tuple[float, float]:
    """Pixel (u, v) of ``point`` in an image of width x height (landscape, ortho).

    Matches Coin's orthographic camera with ADJUST_CAMERA viewport mapping:
    ``camera.height`` is the visible vertical extent when width >= height.
    """
    if width < height:
        raise ValueError("only landscape images are supported")
    rel = g.sub(point, camera.center)
    aspect = width / float(height)
    x = g.dot(rel, camera.right) / (camera.height * aspect)
    y = g.dot(rel, camera.up) / camera.height
    return (0.5 + x) * width, (0.5 - y) * height


def _inside_frame(camera, point, margin=0.1, width=4, height=3):
    u, v = project(camera, point, width, height)
    return margin * width <= u <= (1 - margin) * width and margin * height <= v <= (1 - margin) * height


def select_views(views, max_views: int = 8, angle_tolerance: float = 25.0) -> list[PlannedView]:
    """Drop or merge redundant views, keep the most important ones (max ``max_views``).

    A view is merged into an already kept one when they color the same field,
    look in similar directions, the new target fits in the kept frame and the
    kept frame is not much larger (a close-up is not merged into an overview).
    """
    kept: list[PlannedView] = []
    for view in sorted(views, key=lambda v: (v.priority, -v.score)):
        merged = False
        for i, other in enumerate(kept):
            if other.color_field is not view.color_field:
                continue
            if g.angle_deg(other.camera.direction, view.camera.direction) > angle_tolerance:
                continue
            if other.camera.height > 2.5 * view.camera.height:
                continue
            if all(_inside_frame(other.camera, t.center) for t in view.targets):
                merged = other.targets + tuple(t for t in view.targets if t not in other.targets)
                kept[i] = replace(other, targets=merged)  # no repeated target (no twin balloons)
                merged = True
                break
        if not merged and len(kept) < max_views:
            kept.append(view)
    return kept


def axes_2d(camera: CameraSpec) -> list[tuple[str, float, float]]:
    """World X, Y, Z as seen in the image: (label, du, dv) with |(du, dv)| <= 1
    (shorter when the axis points toward the viewer); v grows downward."""
    out = []
    for label, axis in (("X", Vec3(1, 0, 0)), ("Y", Vec3(0, 1, 0)), ("Z", Vec3(0, 0, 1))):
        out.append((label, g.dot(axis, camera.right), -g.dot(axis, camera.up)))
    return out


def scale_bar(camera: CameraSpec, width: int, height: int, share: float = 0.18):
    """(length in model units, length in pixels) of a round scale bar
    (1, 2 or 5 x 10^k) about ``share`` of the image width (orthographic view)."""
    px_per_unit = height / camera.height
    raw = share * width / px_per_unit
    if raw <= 0:
        return 0.0, 0.0
    power = 10.0 ** math.floor(math.log10(raw))
    length = next(step * power for step in (5.0, 2.0, 1.0) if step * power <= raw)
    return length, length * px_per_unit


def recenter(camera: CameraSpec, target: Vec3, points, width: int, height: int,
             keep: float = 0.35) -> CameraSpec:
    """Shift a close-up so the part fills the frame, keeping ``target`` within
    ``keep`` (fraction of the half-size) of the center.

    A point on the edge of the part, framed at the image center, leaves half of
    the picture empty; centering on the part's visible extent avoids it.
    """
    w, h = width, height
    inside = [project(camera, p, w, h) for p in points]
    inside = [(u, v) for u, v in inside if 0 <= u <= w and 0 <= v <= h]
    if not inside:
        return camera
    cu = 0.5 * (min(u for u, _ in inside) + max(u for u, _ in inside))
    cv = 0.5 * (min(v for _, v in inside) + max(v for _, v in inside))
    tu, tv = project(camera, target, w, h)
    # new center in pixels, clamped so the target stays near the middle
    nu = min(max(cu, tu - keep * w / 2), tu + keep * w / 2)
    nv = min(max(cv, tv - keep * h / 2), tv + keep * h / 2)
    world_per_px = camera.height / h
    shift = g.add(g.scale(camera.right, (nu - w / 2) * world_per_px),
                  g.scale(camera.up, -(nv - h / 2) * world_per_px))
    return replace(camera, center=g.add(camera.center, shift))
