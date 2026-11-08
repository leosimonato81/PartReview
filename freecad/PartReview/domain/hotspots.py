# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Points of interest of a FEM result: what each report view must aim at."""

from collections import deque
from dataclasses import dataclass, replace
from enum import Enum

from . import geometry as g
from .models import Constraint, ConstraintKind, FieldKind, MeshInfo, ResultField, Vec3
from .surface import Surface
from .units import Quantity


class HotspotKind(Enum):
    STRESS_MAX = "stress_max"
    STRESS_REGULAR = "stress_regular"  # max von Mises away from supports and loads
    STRESS = "stress"
    DISPLACEMENT_MAX = "displacement_max"
    GRADIENT = "gradient"
    SUPPORT = "support"
    LOAD = "load"


# Lower number = more important when views must be dropped.
PRIORITY = {
    HotspotKind.STRESS_MAX: 1,
    HotspotKind.STRESS_REGULAR: 2,
    HotspotKind.DISPLACEMENT_MAX: 3,
    HotspotKind.STRESS: 4,
    HotspotKind.GRADIENT: 5,
    HotspotKind.SUPPORT: 6,
    HotspotKind.LOAD: 7,
}


@dataclass(frozen=True)
class Hotspot:
    kind: HotspotKind
    center: Vec3
    radius: float
    normal: Vec3 | None
    sample_points: tuple[Vec3, ...]
    color_field: FieldKind
    peak_node: int | None = None
    peak_value: Quantity | None = None
    label: str = ""  # user label for supports/loads: never translated
    singularity_near: str = ""  # label of the constraint it touches, if any
    sharp_corner: bool = False  # on a sharp re-entrant edge (Williams): likely singular
    # Points ON the part where the balloon leaders point (one per face/edge group of a
    # support or load). Empty: the leader points at ``center``.
    anchors: tuple[Vec3, ...] = ()

    @property
    def leader_points(self) -> tuple[Vec3, ...]:
        return self.anchors or (self.center,)

    @property
    def priority(self) -> int:
        return PRIORITY[self.kind]


def find_clusters(selected, neighbors) -> list[set]:
    """Connected groups of ``selected`` nodes using the ``neighbors`` graph."""
    selected = set(selected)
    seen = set()
    clusters = []
    for start in selected:
        if start in seen:
            continue
        group = {start}
        seen.add(start)
        queue = deque([start])
        while queue:  # terminates: every node is enqueued at most once (seen)
            node = queue.popleft()
            for other in neighbors.get(node, ()):
                if other in selected and other not in seen:
                    seen.add(other)
                    group.add(other)
                    queue.append(other)
        clusters.append(group)
    return clusters


def _cluster_normal(nodes, surface: Surface) -> Vec3 | None:
    total = Vec3(0.0, 0.0, 0.0)
    for node in nodes:
        n = surface.normals.get(node)
        if n is not None:
            total = g.add(total, n)
    return g.normalize(total) if g.length(total) > 1e-9 else None


def _samples(peak, nodes, positions, count=6) -> tuple[Vec3, ...]:
    """Peak plus nodes spread from near to far from the peak."""
    others = sorted((n for n in nodes if n != peak),
                    key=lambda n: g.distance(positions[n], positions[peak]))
    if len(others) > count:
        step = len(others) / float(count)
        others = [others[int(i * step)] for i in range(count)]
    return tuple([positions[peak]] + [positions[n] for n in others])


def _model_radius(mesh: MeshInfo) -> float:
    low, high = mesh.bounding_box()
    return 0.5 * g.distance(low, high)


def _make_hotspot(kind, cluster, values, unit, mesh, surface, color_field):
    positions = mesh.node_positions
    peak = max(cluster, key=values.__getitem__)
    spread = max(g.distance(positions[n], positions[peak]) for n in cluster)
    radius = min(max(spread, 2.0 * surface.mean_edge_length), 0.25 * _model_radius(mesh))
    return Hotspot(
        kind=kind,
        center=positions[peak],
        radius=radius,
        normal=_cluster_normal(cluster, surface),
        sample_points=_samples(peak, cluster, positions),
        color_field=color_field,
        peak_node=peak,
        peak_value=Quantity(values[peak], unit),
    )


def field_hotspots(field: ResultField, mesh: MeshInfo, surface: Surface,
                   threshold_ratio: float = 0.6, max_count: int = 3) -> list[Hotspot]:
    """Clusters of surface nodes above ``threshold_ratio`` of the field range.

    The first hotspot is the field maximum (STRESS_MAX / DISPLACEMENT_MAX);
    for stress, up to ``max_count - 1`` further clusters become STRESS.
    """
    values = {n: v for n, v in zip(field.node_ids, field.values) if n in surface.nodes}
    if not values:
        return []
    vmin, vmax = min(values.values()), max(values.values())
    if vmax <= vmin:
        return []
    threshold = vmin + threshold_ratio * (vmax - vmin)
    clusters = find_clusters((n for n, v in values.items() if v >= threshold), surface.neighbors)
    clusters.sort(key=lambda c: max(values[n] for n in c), reverse=True)

    if field.kind is FieldKind.DISPLACEMENT:
        kinds = [HotspotKind.DISPLACEMENT_MAX]
    else:
        kinds = [HotspotKind.STRESS_MAX] + [HotspotKind.STRESS] * (max_count - 1)
    return [_make_hotspot(kind, cluster, values, field.unit, mesh, surface, field.kind)
            for kind, cluster in zip(kinds, clusters)]


def regular_stress_hotspot(field: ResultField, mesh: MeshInfo, surface: Surface,
                           constraints, exclusion: float, corners=()) -> Hotspot | None:
    """Highest von Mises on the surface farther than ``exclusion`` from every
    support and load (Saint-Venant: an idealised support or load disturbs the
    stress only near it; there the stress may be a singularity that grows with
    refinement). Sharp re-entrant edges (``corners``: segments) are kept away
    from as well (Williams). None when the global maximum is already that far,
    or no node is.

    Walks the nodes from the highest value down and stops at the first one far
    enough, so only a few distances are computed on usual models.
    """
    if not (constraints or corners) or exclusion <= 0:
        return None
    values = {n: v for n, v in zip(field.node_ids, field.values) if n in surface.nodes}
    positions = mesh.node_positions
    for rank, node in enumerate(sorted(values, key=values.__getitem__, reverse=True)):
        p = positions[node]
        if all(distance_to_constraint(p, c) > exclusion for c in constraints) \
                and not near_segments(p, corners, exclusion):
            if rank == 0:
                return None  # the maximum itself is regular: nothing to add
            spot = _make_hotspot(HotspotKind.STRESS_REGULAR, {node}, values, field.unit,
                                 mesh, surface, field.kind)
            return spot
    return None


def gradient_hotspot(field: ResultField, mesh: MeshInfo, surface: Surface,
                     top_fraction: float = 0.02) -> Hotspot | None:
    """Region where the field changes fastest along the surface."""
    values = {n: v for n, v in zip(field.node_ids, field.values) if n in surface.nodes}
    positions = mesh.node_positions
    gradient = {}
    for node, value in values.items():
        best = 0.0
        for other in surface.neighbors.get(node, ()):
            if other in values:
                d = g.distance(positions[node], positions[other])
                if d > 0:
                    best = max(best, abs(values[other] - value) / d)
        gradient[node] = best
    if not gradient or max(gradient.values()) <= 0:
        return None
    ordered = sorted(gradient.values(), reverse=True)
    threshold = ordered[max(0, int(len(ordered) * top_fraction) - 1)]
    clusters = find_clusters((n for n, v in gradient.items() if v >= threshold and v > 0),
                             surface.neighbors)
    best_cluster = max(clusters, key=lambda c: max(gradient[n] for n in c))
    unit = "%s/%s" % (field.unit, mesh.length_unit)
    return _make_hotspot(HotspotKind.GRADIENT, best_cluster, gradient, unit, mesh, surface,
                         field.kind)


def _triangle_normal_area(tri):
    a, b, c = tri
    return g.cross(g.sub(b, a), g.sub(c, a))  # length = 2 * area


MAX_ANCHORS = 6


def _groups(items, keys):
    """Connected groups of items (triangles or segments) that share a vertex."""
    parent = list(range(len(items)))

    def root(i):
        for _ in range(len(items)):  # bounded path walk (rule 6)
            if parent[i] == i:
                break
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first_owner = {}
    for index, item in enumerate(items):
        for k in keys(item):
            if k in first_owner:
                a, b = root(index), root(first_owner[k])
                if a != b:
                    parent[a] = b
            else:
                first_owner[k] = index
    groups = {}
    for index, item in enumerate(items):
        groups.setdefault(root(index), []).append(item)
    return list(groups.values())


def _surface_anchor(triangles):
    """(point on the triangles nearest their area-weighted centroid, area).

    The centroid of a curved or L-shaped face can lie in the air; the centroid of
    the triangle closest to it always lies on the face.
    """
    weighted, area_sum = Vec3(0.0, 0.0, 0.0), 0.0
    for tri in triangles:
        area = g.length(_triangle_normal_area(tri)) / 2.0
        weighted = g.add(weighted, g.scale(g.centroid(tri), area))
        area_sum += area
    if area_sum <= 0:
        return None, 0.0
    c = g.scale(weighted, 1.0 / area_sum)
    best = min(triangles, key=lambda tri: g.point_triangle_distance(c, *tri))
    return g.centroid(best), area_sum


def _line_anchor(segments):
    """(midpoint of the segment nearest the group's middle, length)."""
    length = sum(g.distance(a, b) for a, b in segments)
    mid = g.scale(g.add(*segments[0]), 0.5) if length == 0 else None
    if mid is None:
        weighted = Vec3(0.0, 0.0, 0.0)
        for a, b in segments:
            weighted = g.add(weighted, g.scale(g.add(a, b), 0.5 * g.distance(a, b)))
        c = g.scale(weighted, 1.0 / length)
        a, b = min(segments, key=lambda s: g.point_segment_distance(c, *s))
        mid = g.scale(g.add(a, b), 0.5)
    return mid, length


def _key(p):
    return (round(p.x, 6), round(p.y, 6), round(p.z, 6))


def constraint_hotspot(constraint: Constraint) -> Hotspot | None:
    """Support/load region: one anchor ON the part per face, edge or vertex group."""
    if not (constraint.geometry or constraint.lines or constraint.points):
        return None
    if constraint.kind is ConstraintKind.FIXED or constraint.kind is ConstraintKind.DISPLACEMENT:
        kind = HotspotKind.SUPPORT
    else:
        kind = HotspotKind.LOAD
    anchors = []  # (size, point): faces by area, edges by length, vertices last
    for group in _groups(list(constraint.geometry), lambda tri: [_key(p) for p in tri]):
        point, area = _surface_anchor(group)
        if point is not None:
            anchors.append((area, point))
    for group in _groups(list(constraint.lines), lambda seg: [_key(p) for p in seg]):
        point, length = _line_anchor(group)
        anchors.append((length, point))
    anchors += [(0.0, p) for p in constraint.points]
    anchors.sort(key=lambda a: -a[0])
    points = tuple(p for _, p in anchors[:MAX_ANCHORS])
    center = points[0]
    vertices = ([p for tri in constraint.geometry for p in tri]
                + [p for seg in constraint.lines for p in seg] + list(constraint.points))
    radius = max(g.distance(center, p) for p in vertices) if vertices else 0.0
    normal_sum = Vec3(0.0, 0.0, 0.0)
    for tri in constraint.geometry:
        normal_sum = g.add(normal_sum, _triangle_normal_area(tri))
    centroids = [g.centroid(tri) for tri in constraint.geometry]
    step = max(1, len(centroids) // 6)
    return Hotspot(
        kind=kind,
        center=center,
        radius=radius,
        normal=g.normalize(normal_sum) if g.length(normal_sum) > 1e-9 else None,
        sample_points=tuple(list(points) + centroids[::step][:6]),
        color_field=FieldKind.VON_MISES,
        label=constraint.label,
        anchors=points,
    )


def distance_to_constraint(point: Vec3, constraint: Constraint) -> float:
    """Distance to the faces, edges or vertices the constraint acts on."""
    return min([g.point_triangle_distance(point, *tri) for tri in constraint.geometry]
               + [g.point_segment_distance(point, *seg) for seg in constraint.lines]
               + [g.distance(point, v) for v in constraint.points], default=float("inf"))


def drop_redundant(hotspots) -> list[Hotspot]:
    """Remove secondary stress/gradient hotspots that sit inside a more important one."""
    kept: list[Hotspot] = []
    for spot in sorted(hotspots, key=lambda h: h.priority):
        if spot.kind in (HotspotKind.STRESS, HotspotKind.GRADIENT) and any(
                k.color_field is spot.color_field
                and g.distance(k.center, spot.center) <= max(k.radius, spot.radius)
                for k in kept):
            continue
        kept.append(spot)
    return kept


def near_segments(point: Vec3, segments, distance: float) -> bool:
    return any(g.point_segment_distance(point, a, b) <= distance for a, b in segments)


def mark_singularities(hotspots, constraints, tolerance: float, corners=()) -> list[Hotspot]:
    """Flag stress hotspots that sit on a support or load, or on a sharp
    re-entrant edge (``corners``: segments), as likely singular."""
    marked = []
    for spot in hotspots:
        if spot.kind in (HotspotKind.STRESS_MAX, HotspotKind.STRESS) and spot.peak_node is not None:
            for c in constraints:
                if distance_to_constraint(spot.center, c) <= tolerance:
                    spot = replace(spot, singularity_near=c.label)
                    break
            if not spot.singularity_near and near_segments(spot.center, corners, tolerance):
                spot = replace(spot, sharp_corner=True)
        marked.append(spot)
    return marked
