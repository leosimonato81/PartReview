# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Plain data models for FEM results and the report configuration.

Adapters build these objects from the FreeCAD document; everything above the
adapter layer only sees these models.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, NamedTuple

from .units import Quantity


class Vec3(NamedTuple):
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class NodeValue:
    """A field value at one mesh node, with the node position."""

    node_id: int
    position: Vec3
    value: Quantity


@dataclass(frozen=True)
class MeshInfo:
    node_count: int
    element_count: int
    element_order: int  # 1 = linear, 2 = quadratic
    length_unit: str
    node_positions: Mapping[int, Vec3] = field(repr=False)

    def __post_init__(self):
        if self.element_order not in (1, 2):
            raise ValueError("element_order must be 1 or 2, got %r" % (self.element_order,))
        if len(self.node_positions) != self.node_count:
            raise ValueError("node_count=%d but %d positions given"
                             % (self.node_count, len(self.node_positions)))

    def bounding_box(self) -> tuple[Vec3, Vec3]:
        if not self.node_positions:
            raise ValueError("mesh has no nodes")
        xs, ys, zs = zip(*self.node_positions.values())
        return Vec3(min(xs), min(ys), min(zs)), Vec3(max(xs), max(ys), max(zs))


class FieldKind(Enum):
    VON_MISES = "von_mises"
    DISPLACEMENT = "displacement"
    ESTIMATED_ERROR = "estimated_error"  # derived: ZZ local error indicator (decision 005)


@dataclass(frozen=True)
class ResultField:
    """One scalar value per node (e.g. von Mises stress, displacement magnitude)."""

    kind: FieldKind
    unit: str
    node_ids: tuple[int, ...] = field(repr=False)
    values: tuple[float, ...] = field(repr=False)

    def __post_init__(self):
        if len(self.node_ids) != len(self.values):
            raise ValueError("node_ids (%d) and values (%d) differ in length"
                             % (len(self.node_ids), len(self.values)))
        if not self.values:
            raise ValueError("field %s has no values" % self.kind.value)

    def _node_value(self, index: int, mesh: MeshInfo) -> NodeValue:
        node_id = self.node_ids[index]
        return NodeValue(node_id, mesh.node_positions[node_id],
                         Quantity(self.values[index], self.unit))

    def maximum(self, mesh: MeshInfo) -> NodeValue:
        index = max(range(len(self.values)), key=self.values.__getitem__)
        return self._node_value(index, mesh)

    def minimum(self, mesh: MeshInfo) -> NodeValue:
        index = min(range(len(self.values)), key=self.values.__getitem__)
        return self._node_value(index, mesh)


@dataclass(frozen=True)
class Material:
    name: str
    youngs_modulus: Quantity | None = None
    poisson_ratio: float | None = None
    density: Quantity | None = None
    yield_strength: Quantity | None = None


class ConstraintKind(Enum):
    FIXED = "fixed"
    FORCE = "force"
    PRESSURE = "pressure"
    DISPLACEMENT = "displacement"
    OTHER = "other"


@dataclass(frozen=True)
class Constraint:
    kind: ConstraintKind
    label: str  # user text: never translated
    references: tuple[str, ...] = ()  # e.g. ("Shroud 001:Face2",)
    magnitude: Quantity | None = None
    direction: Vec3 | None = None
    # Tessellated CAD faces the constraint acts on (mesh length unit).
    geometry: tuple[tuple[Vec3, Vec3, Vec3], ...] = field(default=(), repr=False)
    # Discretised CAD edges and vertices it acts on: line/point supports and loads.
    lines: tuple[tuple[Vec3, Vec3], ...] = field(default=(), repr=False)
    points: tuple[Vec3, ...] = field(default=(), repr=False)

    @property
    def on_edges_or_vertices(self) -> bool:
        """Acts on a line or a point: theoretically infinite stress there."""
        return any(":Edge" in r or ":Vertex" in r for r in self.references)


@dataclass(frozen=True)
class FemResult:
    """Everything the report needs from one FEM analysis result."""

    label: str
    solver: str
    analysis_type: str
    mesh: MeshInfo
    fields: Mapping[FieldKind, ResultField]
    materials: tuple[Material, ...] = ()
    constraints: tuple[Constraint, ...] = ()
    elements: tuple[tuple[int, ...], ...] = field(default=(), repr=False)  # volume elements

    def get_field(self, kind: FieldKind) -> ResultField | None:
        return self.fields.get(kind)


SUPPORTED_LANGUAGES = ("pt_BR", "en")


class ReportLevel(Enum):
    """How much the report contains (owner's request, phase 6a)."""

    QUICK = "quick"  # quick summary, about 2 pages
    STANDARD = "standard"  # intermediate
    FULL = "full"  # complete


class UnitSystem(Enum):
    """How values are shown in the report (decision 002)."""

    MPA_MM = "mpa_mm"  # fixed engineering units: MPa, mm, N, kg/m^3
    FREECAD_SCHEMA = "freecad_schema"  # user's unit schema from FreeCAD preferences


@dataclass
class ReportConfig:
    """The single source of truth for report options (CLAUDE.md rule 2).

    Widgets read and write this object; they never copy state between them.
    """

    result_name: str = ""  # FreeCAD internal object name of the chosen result
    language: str = "pt_BR"
    unit_system: UnitSystem = UnitSystem.MPA_MM
    title: str = ""  # user text: never translated
    author: str = ""
    notes: str = ""
    output_path: str = ""
    yield_strength: str = ""  # optional, as typed by the user, e.g. "250 MPa"
    max_views: int = 8
    level: ReportLevel = ReportLevel.FULL
    company: str = ""  # user text: never translated
    logo_path: str = ""  # optional image for the cover
    accent_color: str = ""  # "#rrggbb" from a template; empty = default
    intro_text: str = ""  # user text shown in the executive summary
    disclaimer_text: str = ""  # user text shown with the assumptions
    export_csv: bool = False  # nodal values next to the PDF
    export_html: bool = False  # HTML version of the report next to the PDF
    # Supports-and-loads figure (owner: optional, not in the quick summary).
    show_boundary: bool = True

    @property
    def includes_boundary(self) -> bool:
        return self.show_boundary and self.level is not ReportLevel.QUICK

    def extra_output(self, extension: str) -> str:
        """Path of an extra export: the PDF path with another extension."""
        base = self.output_path[:-4] if self.output_path.lower().endswith(".pdf") else \
            self.output_path
        return base + extension

    def validate(self) -> list[str]:
        """Return i18n keys of problems; an empty list means valid."""
        errors = []
        if not self.result_name:
            errors.append("config.error.no_result")
        if self.language not in SUPPORTED_LANGUAGES:
            errors.append("config.error.language")
        if not isinstance(self.unit_system, UnitSystem):
            errors.append("config.error.unit_system")
        if not isinstance(self.level, ReportLevel):
            errors.append("config.error.level")
        if self.accent_color and not (len(self.accent_color) == 7 and self.accent_color[0] == "#"):
            errors.append("template.error.color")
        if not 2 <= self.max_views <= 12:
            errors.append("config.error.max_views")
        if not self.output_path:
            errors.append("config.error.no_output")
        elif not self.output_path.lower().endswith(".pdf"):
            errors.append("config.error.output_not_pdf")
        return errors
