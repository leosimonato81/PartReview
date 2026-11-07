# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Occlusion test: is a surface point visible from a view direction?

Casts a ray from the point toward the camera and checks it against every
outer-surface triangle (Moller-Trumbore, vectorised with numpy, which ships
with FreeCAD). Lives in adapters because domain/ stays dependency-free.
"""

import numpy as np  # type: ignore


class RayVisibility:
    """Callable ``(point, view_direction) -> bool`` for camera_planner."""

    def __init__(self, positions, triangles, epsilon):
        if not triangles:
            raise ValueError("RayVisibility needs at least one triangle")
        lookup = {nid: i for i, nid in enumerate(positions)}
        coords = np.array([tuple(positions[n]) for n in positions], dtype=np.float64)
        index = np.array([[lookup[n] for n in tri] for tri in triangles], dtype=np.int64)
        self._v0 = coords[index[:, 0]]
        self._e1 = coords[index[:, 1]] - self._v0
        self._e2 = coords[index[:, 2]] - self._v0
        self._eps = float(epsilon)
        self._cache = {}

    @property
    def triangle_count(self):
        return len(self._v0)

    def __call__(self, point, direction):
        key = (tuple(point), tuple(direction))
        if key not in self._cache:
            self._cache[key] = self._visible(point, direction)
        return self._cache[key]

    def _visible(self, point, direction):
        d = -np.asarray(direction, dtype=np.float64)  # from the point toward the camera
        d /= np.linalg.norm(d)
        origin = np.asarray(point, dtype=np.float64) + d * self._eps
        h = np.cross(d, self._e2)
        a = np.einsum("ij,ij->i", self._e1, h)
        ok = np.abs(a) > 1e-12
        f = np.zeros_like(a)
        f[ok] = 1.0 / a[ok]
        s = origin - self._v0
        u = f * np.einsum("ij,ij->i", s, h)
        q = np.cross(s, self._e1)
        v = f * (q @ d)
        t = f * np.einsum("ij,ij->i", self._e2, q)
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > self._eps)
        return not bool(hit.any())
