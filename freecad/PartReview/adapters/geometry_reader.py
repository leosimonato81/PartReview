# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Read a solid with the Part API and summarise it for the mesh assistant."""

import Part  # type: ignore

from ..domain.geometry_summary import GeometrySummary, WallSample

MAX_PLANAR_FACES = 400  # wall search is pairwise: keep it bounded on big models
EDGES_KEPT = 30


def solid_shape(obj):
    """Shape of ``obj`` in global coordinates (works inside App::Part and links)."""
    return Part.getShape(obj, "", needSubElement=False, refine=False)


def is_meshable(obj):
    try:
        shape = solid_shape(obj)
    except (ValueError, RuntimeError, Part.OCCError):
        return False
    return not shape.isNull() and bool(shape.Solids)


def _radius(surface):
    for attribute in ("Radius", "MinorRadius"):
        value = getattr(surface, attribute, None)
        if isinstance(value, float):
            return value
    return None


def summarize(obj) -> GeometrySummary:
    shape = solid_shape(obj)
    bb = shape.BoundBox
    edges = sorted((e.Length, "Edge%d" % (i + 1)) for i, e in enumerate(shape.Edges))
    radii = []
    planes = []
    for i, face in enumerate(shape.Faces):
        surface = face.Surface
        r = _radius(surface)
        if r is not None:
            radii.append((r, "Face%d" % (i + 1)))
        if type(surface).__name__ == "Plane":
            planes.append(("Face%d" % (i + 1), face, face.normalAt(0, 0),
                           surface.Position))
    t = 2.0 * shape.Volume / shape.Area if shape.Area > 0 else 0.0
    walls = []
    planes = planes[:MAX_PLANAR_FACES]
    for a in range(len(planes)):
        name_a, face_a, n_a, p_a = planes[a]
        for b in range(a + 1, len(planes)):
            name_b, face_b, n_b, p_b = planes[b]
            if n_a.dot(n_b) > -0.999:
                continue
            gap = abs((p_b - p_a).dot(n_a))
            if gap <= 1e-6 or gap > t:  # only walls up to the characteristic thickness
                continue
            if abs(face_a.distToShape(face_b)[0] - gap) < 1e-3 * max(1.0, gap):
                walls.append(WallSample(gap, (name_a, name_b)))
    walls.sort(key=lambda w: w.thickness)
    return GeometrySummary(
        name=obj.Name, label=obj.Label, size=(bb.XLength, bb.YLength, bb.ZLength),
        volume=shape.Volume, area=shape.Area, faces=len(shape.Faces), edges=len(shape.Edges),
        valid=shape.isValid(), shortest_edges=tuple(edges[:EDGES_KEPT]),
        radii=tuple(sorted(radii)), walls=tuple(walls))
