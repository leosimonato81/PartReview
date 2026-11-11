# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Degenerate tetrahedra in a mesh, before CalculiX sees it.

CalculiX refuses a mesh with "nonpositive jacobian determinant" when the
isoparametric map of an element folds or flattens. A1b (2026-11-11): Gmsh left a
FLAT 10-node tetrahedron (four corners in one plane, joining the two faces of a
thin plate) that the corner-volume statistics of domain/quality.py did not stop.
Here the Jacobian determinant of every element is evaluated at its corners,
mid-edges, centroid and Gauss points: an element is degenerate when, at any of
these points, the determinant is zero or has the sign opposite to the mesh's
prevailing one (the same condition CalculiX checks, at more points).
Uses numpy (ships with FreeCAD), hence lives in adapters.
"""

import numpy as np  # type: ignore

from .error_estimator import RULES, _tet4, _tet10

_CORNERS = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]]
_EDGES = [[0.5, 0, 0], [0.5, 0.5, 0], [0, 0.5, 0], [0, 0, 0.5], [0.5, 0, 0.5], [0, 0.5, 0.5]]
_SAMPLES = np.array(_CORNERS + _EDGES + [[0.25, 0.25, 0.25]] + RULES[10][0].tolist(),
                    dtype=float)


def degenerate_elements(fem_mesh) -> list:
    """Ids of the degenerate volume elements of a FreeCAD FemMesh (4- or 10-node
    tetrahedra; other element types are not checked)."""
    nodes = fem_mesh.Nodes
    by_size = {4: [], 10: []}
    for eid in fem_mesh.Volumes:
        conn = fem_mesh.getElementNodes(eid)
        if len(conn) in by_size:
            by_size[len(conn)].append((eid, conn))
    found = []
    for size, items in by_size.items():
        if not items:
            continue
        shape = _tet10 if size == 10 else _tet4
        _, dN = shape(_SAMPLES)  # (S, n, 3)
        X = np.array([[(nodes[n].x, nodes[n].y, nodes[n].z) for n in conn]
                      for _, conn in items], dtype=float)  # (E, n, 3)
        det = np.linalg.det(np.einsum("snd,enk->esdk", dN, X))  # (E, S)
        prevailing = np.sign(np.median(det[:, -1]))  # sign at a Gauss point
        if prevailing == 0:
            prevailing = 1.0
        bad = np.any(det * prevailing <= 0.0, axis=1)
        found.extend(items[i][0] for i in np.flatnonzero(bad))
    return found
