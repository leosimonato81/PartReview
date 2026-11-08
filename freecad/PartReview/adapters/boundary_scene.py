# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""3D scene of the supports-and-loads figure: gray part, colored regions, arrows.

Built only from Coin nodes that ViewState adds to the view for the capture and
removes afterwards: nothing in the user's document is touched (no colors, no
visibility, no new objects).
"""

from pivy import coin  # type: ignore

from ..domain import geometry as g
from ..domain.colors import LOAD_RGB, PART_RGB, SUPPORT_RGB
from ..domain.models import ConstraintKind
from ..domain.surface import feature_edges, interior, triangles_on

EDGE_RGB = (70, 70, 70)
ARROW_RGB = (35, 35, 35)  # dark: readable on the orange load faces and on gray
ARROW_LENGTH = 0.12  # of the model radius
ARROW_RADIUS = 0.0045  # shaft radius, of the model radius (head: 2.6x wider)
ARROW_SPACING = 0.2  # minimum distance between arrows of one load, of the radius
ARROWS_PER_LOAD = 4
SUPPORT_KINDS = (ConstraintKind.FIXED, ConstraintKind.DISPLACEMENT)


def _rgb(color):
    return tuple(c / 255.0 for c in color)


def _material(color, lit=True):
    mat = coin.SoMaterial()
    mat.diffuseColor.setValue(*_rgb(color))
    if not lit:
        mat.emissiveColor.setValue(*_rgb(color))
    return mat


def _faces(points, triangles, color, offset):
    """Indexed triangles with their own polygon offset (larger = drawn in front)."""
    sep = coin.SoSeparator()
    hints = coin.SoShapeHints()
    hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
    hints.shapeType = coin.SoShapeHints.UNKNOWN_SHAPE_TYPE  # two-sided lighting
    hints.creaseAngle = 0.6  # smooth on curved faces, sharp on CAD edges
    sep.addChild(hints)
    shift = coin.SoPolygonOffset()
    shift.factor = 1.0 - offset
    shift.units = 1.0 - offset
    sep.addChild(shift)
    sep.addChild(_material(color))
    sep.addChild(points)
    faces = coin.SoIndexedFaceSet()
    index = []
    for tri in triangles:
        index += [tri[0], tri[1], tri[2], -1]
    faces.coordIndex.setValues(0, len(index), index)
    sep.addChild(faces)
    return sep


def _lines(segments, color, width):
    sep = coin.SoSeparator()
    light = coin.SoLightModel()
    light.model = coin.SoLightModel.BASE_COLOR
    sep.addChild(light)
    style = coin.SoDrawStyle()
    style.lineWidth = width
    sep.addChild(style)
    sep.addChild(_material(color, lit=False))
    coords = coin.SoCoordinate3()
    pts = [tuple(p) for seg in segments for p in seg]
    coords.point.setValues(0, len(pts), pts)
    sep.addChild(coords)
    lines = coin.SoLineSet()
    lines.numVertices.setValues(0, len(segments), [2] * len(segments))
    sep.addChild(lines)
    return sep


def _dots(points, color, radius):
    sep = coin.SoSeparator()
    sep.addChild(_material(color))
    for p in points:
        part = coin.SoSeparator()
        move = coin.SoTranslation()
        move.translation.setValue(*p)
        part.addChild(move)
        ball = coin.SoSphere()
        ball.radius = radius
        part.addChild(ball)
        sep.addChild(part)
    return sep


def _arrow(tail, tip, color, radius):
    """Cylinder shaft + cone head from ``tail`` to ``tip``."""
    axis = g.sub(tip, tail)
    length = g.length(axis)
    if length <= 0:
        return None
    d = g.normalize(axis)
    head = min(0.35 * length, 8.0 * radius)
    sep = coin.SoSeparator()
    sep.addChild(_material(color))
    turn = coin.SoTransform()
    turn.rotation.setValue(coin.SbRotation(coin.SbVec3f(0, 1, 0), coin.SbVec3f(*d)))
    turn.translation.setValue(*tail)
    sep.addChild(turn)
    shaft_len = length - head
    shaft = coin.SoSeparator()
    move = coin.SoTranslation()
    move.translation.setValue(0, shaft_len / 2.0, 0)
    shaft.addChild(move)
    cyl = coin.SoCylinder()
    cyl.radius = radius
    cyl.height = shaft_len
    shaft.addChild(cyl)
    sep.addChild(shaft)
    cone_sep = coin.SoSeparator()
    move = coin.SoTranslation()
    move.translation.setValue(0, shaft_len + head / 2.0, 0)
    cone_sep.addChild(move)
    cone = coin.SoCone()
    cone.bottomRadius = 2.6 * radius
    cone.height = head
    cone_sep.addChild(cone)
    sep.addChild(cone_sep)
    return sep


def build(result, surface, model_radius):
    """Coin root of the supports-and-loads scene (mesh coordinates) and a
    function ``show_arrows(labels)`` that keeps only those loads' arrows."""
    positions = result.mesh.node_positions
    ids = sorted({i for tri in surface.triangles for i in tri})
    where = {node: k for k, node in enumerate(ids)}
    points = coin.SoCoordinate3()
    points.point.setValues(0, len(ids), [tuple(positions[i]) for i in ids])
    local = [tuple(where[i] for i in tri) for tri in surface.triangles]

    tolerance = 0.3 * surface.mean_edge_length
    color_of = {}  # triangle index -> color (supports win over loads)
    segments = {SUPPORT_RGB: [], LOAD_RGB: []}
    dots = {SUPPORT_RGB: [], LOAD_RGB: []}
    force_triangles = {}  # force constraint label -> its mesh triangles
    for c in sorted(result.constraints, key=lambda c: c.kind in SUPPORT_KINDS):
        if c.kind not in SUPPORT_KINDS and c.kind not in (ConstraintKind.FORCE,
                                                         ConstraintKind.PRESSURE):
            continue
        color = SUPPORT_RGB if c.kind in SUPPORT_KINDS else LOAD_RGB
        on = triangles_on(c.geometry, surface.triangles, positions, tolerance)
        for t in on:
            color_of[t] = color
        if c.kind is ConstraintKind.FORCE:
            force_triangles[c.label] = sorted(on)
        segments[color] += list(c.lines)
        dots[color] += list(c.points)

    root = coin.SoSeparator()
    plain = [tri for t, tri in enumerate(local) if t not in color_of]
    root.addChild(_faces(points, plain, PART_RGB, 0.0))
    for color in (LOAD_RGB, SUPPORT_RGB):
        tris = [local[t] for t, c in color_of.items() if c == color]
        if tris:
            root.addChild(_faces(points, tris, color, 0.5))
    edges = feature_edges(surface.triangles, positions)
    root.addChild(_lines([(positions[a], positions[b]) for a, b in edges], EDGE_RGB, 1.5))
    for color in (LOAD_RGB, SUPPORT_RGB):  # edge and vertex supports/loads
        if segments[color]:
            root.addChild(_lines(segments[color], color, 6.0))
        if dots[color]:
            root.addChild(_dots(dots[color], color, 0.02 * model_radius))

    # Forces as in FEM programs: a few thin arrows spread over each loaded face
    # (or along the loaded edges), all the same size. A pushing arrow ends on the
    # surface, a pulling one starts on it, so none is hidden inside the part.
    length = ARROW_LENGTH * model_radius
    arrows = {}
    for c in result.constraints:
        if c.kind is not ConstraintKind.FORCE or c.direction is None \
                or g.length(c.direction) == 0:
            continue
        d = g.normalize(c.direction)
        group = coin.SoSwitch()  # shown only in views where this load is visible
        group.whichChild = coin.SO_SWITCH_ALL
        arrows[c.label] = group
        root.addChild(group)
        places = []  # (point, outward normal or None)
        for t in interior(force_triangles.get(c.label, ()), surface.triangles):
            tri = [positions[i] for i in surface.triangles[t]]
            n = g.cross(g.sub(tri[1], tri[0]), g.sub(tri[2], tri[0]))
            places.append((g.centroid(tri), g.normalize(n) if g.length(n) > 0 else None))
        places += [(g.centroid(seg), None) for seg in c.lines]
        places += [(p, None) for p in c.points]
        places = places[::max(1, len(places) // 2000)]  # sampling cost bound
        for k in g.spread([p for p, _ in places], ARROWS_PER_LOAD, ARROW_SPACING * model_radius):
            point, normal = places[k]
            if normal is not None and g.dot(d, normal) > 0:
                tail, tip = point, g.add(point, g.scale(d, length))
            else:
                tail, tip = g.sub(point, g.scale(d, length)), point
            arrow = _arrow(tail, tip, ARROW_RGB, ARROW_RADIUS * model_radius)
            if arrow is not None:
                group.addChild(arrow)
    def show_arrows(labels):
        for label, group in arrows.items():
            group.whichChild = coin.SO_SWITCH_ALL if label in labels else coin.SO_SWITCH_NONE

    return root, show_arrows
