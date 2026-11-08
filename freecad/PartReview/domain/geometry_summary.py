# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""What the mesh assistant knows about a solid BEFORE any mesh exists (pure, no Qt).

Everything is relative to the part itself, so the same rules work for a 10 mm
bracket and a 2 m frame:
- characteristic thickness t = 2 V / A (exact for a plate: V = A t / 2 when the
  two large faces dominate the area; smaller than the wall for chunky parts);
- details much smaller than t are reported as issues, not meshed finely
  (spike 8.0: a 0.3 mm leftover of a cut forced a mesh that froze the PC).
Lengths in mm (FreeCAD's internal length unit), areas in mm^2, volumes in mm^3.
"""

from dataclasses import dataclass, field
from enum import Enum

THIN_WALL_RATIO = 0.25  # wall thinner than t/4: very likely a modelling leftover
SMALL_RADIUS_RATIO = 0.2  # radius below t/5: curvature refinement will be local there
TINY_EDGE_RATIO = 0.1  # edge shorter than t/10


@dataclass(frozen=True)
class WallSample:
    thickness: float  # distance between two opposite parallel faces that overlap
    faces: tuple[str, str]  # e.g. ("Face5", "Face71")


class IssueKind(Enum):
    THIN_WALL = "thin_wall"
    SMALL_RADIUS = "small_radius"
    TINY_EDGE = "tiny_edge"


@dataclass(frozen=True)
class GeometryIssue:
    kind: IssueKind
    size: float  # mm: thickness, radius or edge length
    elements: tuple[str, ...]  # sub-element names to select in the 3D view
    count: int = 1  # how many similar features this issue groups


@dataclass(frozen=True)
class GeometrySummary:
    name: str  # internal object name
    label: str  # user label: never translated
    size: tuple[float, float, float]  # bounding box lengths
    volume: float
    area: float
    faces: int
    edges: int
    valid: bool = True
    shortest_edges: tuple[tuple[float, str], ...] = ()  # (length, "EdgeN"), ascending
    radii: tuple[tuple[float, str], ...] = ()  # (radius, "FaceN") of cylinders/cones/...
    walls: tuple[WallSample, ...] = ()  # ascending thickness

    @property
    def diagonal(self) -> float:
        x, y, z = self.size
        return (x * x + y * y + z * z) ** 0.5

    @property
    def characteristic_thickness(self) -> float:
        """t = 2 V / A."""
        return 2.0 * self.volume / self.area if self.area > 0 else 0.0


def find_issues(summary: GeometrySummary) -> list:
    """Details much smaller than the characteristic thickness, largest problem first."""
    t = summary.characteristic_thickness
    if t <= 0:
        return []
    issues = []
    for wall in summary.walls:
        if wall.thickness < THIN_WALL_RATIO * t:
            issues.append(GeometryIssue(IssueKind.THIN_WALL, wall.thickness, wall.faces))
    small = [(r, f) for r, f in summary.radii if r < SMALL_RADIUS_RATIO * t]
    if small:
        issues.append(GeometryIssue(IssueKind.SMALL_RADIUS, min(r for r, _ in small),
                                    tuple(f for _, f in small), len(small)))
    tiny = [(length, e) for length, e in summary.shortest_edges if length < TINY_EDGE_RATIO * t]
    if tiny:
        issues.append(GeometryIssue(IssueKind.TINY_EDGE, min(x for x, _ in tiny),
                                    tuple(e for _, e in tiny), len(tiny)))
    return issues
