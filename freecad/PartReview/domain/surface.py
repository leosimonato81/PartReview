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
