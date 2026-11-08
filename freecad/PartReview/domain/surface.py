# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Outer surface of a tetrahedral mesh: triangles, outward normals, node graph.

Supports linear (4-node) and quadratic (10-node) tetrahedra in SMESH order:
corners 0-3, then mid-side nodes 4:(0,1) 5:(1,2) 6:(2,0) 7:(0,3) 8:(1,3) 9:(2,3)
(verified against node coordinates of a.FCStd, 2026-11-06).
"""

from dataclasses import dataclass, field
from typing import Mapping

from . import geometry as g
from .models import Vec3

# (corner a, corner b, corner c, opposite corner)
_TET_FACES = ((0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 3, 1), (1, 2, 3, 0))
_TET10_MID = {(0, 1): 4, (1, 2): 5, (0, 2): 6, (0, 3): 7, (1, 3): 8, (2, 3): 9}


@dataclass(frozen=True)
class Surface:
    triangles: tuple[tuple[int, int, int], ...] = field(repr=False)  # outward, corner ids
    nodes: frozenset = field(repr=False)  # all surface node ids (corners + mid-side)
    neighbors: Mapping[int, tuple[int, ...]] = field(repr=False)
    normals: Mapping[int, Vec3] = field(repr=False)  # outward unit normal per surface node
    mean_edge_length: float = 0.0


def _mid(element, i, j):
    return element[_TET10_MID[(min(i, j), max(i, j))]]


def build_surface(elements, positions: Mapping[int, Vec3]) -> Surface:
    """Build the outer surface from tetrahedra given as node-id tuples."""
    face_count = {}
    face_data = {}
    for element in elements:
        if len(element) not in (4, 10):
            raise ValueError("only 4- or 10-node tetrahedra are supported, got %d nodes"
                             % len(element))
        for a, b, c, opposite in _TET_FACES:
            key = tuple(sorted((element[a], element[b], element[c])))
            face_count[key] = face_count.get(key, 0) + 1
            face_data[key] = (element, a, b, c, opposite)

    triangles = []
    links = {}
    normal_sum = {}
    edge_lengths = []

    def link(u, v):
        links.setdefault(u, set()).add(v)
        links.setdefault(v, set()).add(u)

    for key, count in face_count.items():
        if count != 1:
            continue
        element, a, b, c, opposite = face_data[key]
        ia, ib, ic = element[a], element[b], element[c]
        pa, pb, pc = positions[ia], positions[ib], positions[ic]
        n = g.cross(g.sub(pb, pa), g.sub(pc, pa))
        if g.dot(n, g.sub(positions[element[opposite]], pa)) > 0:
            ib, ic, pb, pc = ic, ib, pc, pb
            n = g.scale(n, -1.0)
        triangles.append((ia, ib, ic))
        corners = (ia, ib, ic)
        for node in corners:
            normal_sum[node] = g.add(normal_sum.get(node, Vec3(0.0, 0.0, 0.0)), n)
        for u, v in ((ia, ib), (ib, ic), (ic, ia)):
            edge_lengths.append(g.distance(positions[u], positions[v]))
            if len(element) == 10:
                local = {element[k]: k for k in (a, b, c)}
                m = _mid(element, local[u], local[v])
                link(u, m)
                link(m, v)
                normal_sum[m] = g.add(normal_sum.get(m, Vec3(0.0, 0.0, 0.0)), n)
            else:
                link(u, v)

    normals = {}
    for node, total in normal_sum.items():
        if g.length(total) > 0:
            normals[node] = g.normalize(total)
    return Surface(
        triangles=tuple(triangles),
        nodes=frozenset(links),
        neighbors={k: tuple(v) for k, v in links.items()},
        normals=normals,
        mean_edge_length=sum(edge_lengths) / len(edge_lengths) if edge_lengths else 0.0,
    )


def feature_edges(triangles, positions: Mapping[int, Vec3],
                  angle_deg: float = 30.0) -> list[tuple[int, int]]:
    """Corner-node pairs where the surface folds by more than ``angle_deg``.

    These are the part's visible outline (CAD edges) on a picture without the
    mesh lines. Edges with only one triangle (open surface) are kept too.
    """
    normal = {}
    by_edge = {}
    for tri in triangles:
        pa, pb, pc = (positions[i] for i in tri)
        n = g.cross(g.sub(pb, pa), g.sub(pc, pa))
        normal[tri] = g.normalize(n) if g.length(n) > 0 else None
        for u, v in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            by_edge.setdefault((min(u, v), max(u, v)), []).append(tri)
    edges = []
    for edge, tris in by_edge.items():
        if len(tris) != 2:
            edges.append(edge)
            continue
        n1, n2 = normal[tris[0]], normal[tris[1]]
        if n1 is None or n2 is None or g.angle_deg(n1, n2) > angle_deg:
            edges.append(edge)
    return edges


def _cell(point, size):
    return (int(point[0] // size), int(point[1] // size), int(point[2] // size))


def _grid(geometry, tolerance):
    """(cell size, cell -> indices of the triangles whose box, grown by
    ``tolerance``, meets the cell): a point then only meets its cell's triangles."""
    lows = [tuple(min(p[k] for p in tri) for k in range(3)) for tri in geometry]
    highs = [tuple(max(p[k] for p in tri) for k in range(3)) for tri in geometry]
    span = max([highs[n][k] - lows[n][k] for n in range(len(geometry)) for k in range(3)]
               + [0.0])
    size = max(4.0 * tolerance, span / 40.0)
    grid = {}
    for n, (lo, hi) in enumerate(zip(lows, highs)):
        a = _cell(tuple(v - tolerance for v in lo), size)
        b = _cell(tuple(v + tolerance for v in hi), size)
        for i in range(a[0], b[0] + 1):
            for j in range(a[1], b[1] + 1):
                for k in range(a[2], b[2] + 1):
                    grid.setdefault((i, j, k), []).append(n)
    return size, grid


def triangles_on(geometry, triangles, positions: Mapping[int, Vec3], tolerance: float,
                 min_cos: float = 0.7) -> set[int]:
    """Indices of mesh ``triangles`` lying on the CAD faces given as ``geometry``.

    A mesh triangle is on a face when its centroid is within ``tolerance`` of
    one of the face's tessellation triangles AND both are nearly parallel
    (|cos| >= ``min_cos``): the second test drops the triangles of a
    perpendicular neighbor face that only touch the shared edge. The face
    orientation is not trusted (tessellation may be reversed), hence |cos|.
    A grid of cells keeps it fast: each mesh triangle is compared only with the
    face triangles of its cell.
    """
    if not geometry or not triangles or tolerance <= 0:
        return set()
    cell, grid = _grid(geometry, tolerance)
    face_normals = []
    for tri in geometry:
        n = g.cross(g.sub(tri[1], tri[0]), g.sub(tri[2], tri[0]))
        face_normals.append(g.normalize(n) if g.length(n) > 0 else None)

    found = set()
    for t, tri in enumerate(triangles):
        pa, pb, pc = (positions[i] for i in tri)
        c = g.centroid((pa, pb, pc))
        candidates = grid.get(_cell(c, cell))
        if not candidates:
            continue
        n = g.cross(g.sub(pb, pa), g.sub(pc, pa))
        if g.length(n) == 0:
            continue
        n = g.normalize(n)
        for f in candidates:
            fn = face_normals[f]
            if fn is None or abs(g.dot(n, fn)) < min_cos:
                continue
            if g.point_triangle_distance(c, *geometry[f]) <= tolerance:
                found.add(t)
                break
    return found


def nearest_faces(triangles, positions: Mapping[int, Vec3], faces, wanted,
                  tolerance: float) -> dict[int, str]:
    """Mesh triangle index -> name of the ``wanted`` CAD face it lies on.

    ``faces`` maps every face name of the part to its tessellation triangles.
    A mesh triangle near a wanted face (centroid within ``tolerance``) is given
    to the CLOSEST face of the whole part: on a fillet or a chamfer next to a
    loaded face, the boundary of the painting then follows the CAD edge
    instead of a jagged line.
    """
    wanted = [w for w in wanted if faces.get(w)]
    if not wanted or not triangles or tolerance <= 0:
        return {}
    near = {}
    for name in wanted:  # candidates: mesh triangles close to a wanted face
        for t in triangles_on(faces[name], triangles, positions, tolerance, min_cos=-1.0):
            near.setdefault(t, set()).add(name)
    if not near:
        return {}
    centroids = {t: g.centroid([positions[i] for i in triangles[t]]) for t in near}
    lo = [min(c[k] for c in centroids.values()) - tolerance for k in range(3)]
    hi = [max(c[k] for c in centroids.values()) + tolerance for k in range(3)]

    def touches(tri):  # face triangle bounding box meets the candidates' region
        return all(min(p[k] for p in tri) <= hi[k] and max(p[k] for p in tri) >= lo[k]
                   for k in range(3))

    named = [(name, tri) for name, geo in faces.items() for tri in geo if touches(tri)]
    cell, grid = _grid([tri for _, tri in named], tolerance)
    result = {}
    for t, c in centroids.items():
        best, best_d = None, float("inf")
        # the wanted face is within tolerance, so the nearest one is too: the
        # centroid's cell holds every face triangle that can be the nearest
        for k in grid.get(_cell(c, cell), ()):
            name, tri = named[k]
            d = g.point_triangle_distance(c, *tri)
            if d < best_d:
                best, best_d = name, d
        if best in near[t]:
            result[t] = best
    return result


def reentrant_edges(triangles, positions: Mapping[int, Vec3],
                    min_angle_deg: float = 60.0) -> list[tuple[int, int]]:
    """Sharp concave (re-entrant) edges: where the outer surface folds INTO the
    part by more than ``min_angle_deg`` without a fillet.

    Linear elasticity (Williams 1952): at a re-entrant corner the stress is
    theoretically infinite, so the FE value there grows with refinement, like
    at a support on an edge. A convex edge (an outer corner) is harmless.
    Concave test: across the edge, the neighbor triangle's far corner lies on
    the outer side of this triangle (``triangles`` must be outward-oriented,
    as built by ``build_surface``).
    """
    by_edge = {}
    for tri in triangles:
        for k in range(3):
            u, v, w = tri[k], tri[(k + 1) % 3], tri[(k + 2) % 3]
            by_edge.setdefault((min(u, v), max(u, v)), []).append((tri, w))
    edges = []
    for (u, v), pair in by_edge.items():
        if len(pair) != 2:
            continue
        (t1, _), (t2, far2) = pair
        p = [positions[i] for i in t1]
        n1 = g.cross(g.sub(p[1], p[0]), g.sub(p[2], p[0]))
        q = [positions[i] for i in t2]
        n2 = g.cross(g.sub(q[1], q[0]), g.sub(q[2], q[0]))
        if g.length(n1) == 0 or g.length(n2) == 0:
            continue
        if g.angle_deg(n1, n2) <= min_angle_deg:
            continue
        if g.dot(n1, g.sub(positions[far2], positions[u])) > 0:  # folds inward
            edges.append((u, v))
    return edges
