# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""FEM report content: the FEM sections registered in the section engine.

What to say lives here; how to draw it lives in the PDF/HTML renderers. All
tool texts come from the Translator; user texts (title, author, company,
labels) are copied as they are.
"""

import datetime
import math
from dataclasses import dataclass, field, replace

from . import colormap
from . import geometry as g
from .blocks import (  # noqa: F401  (re-exported for callers and tests)
    DEFAULT_ACCENT,
    BarChart,
    BulletList,
    Cover,
    Document,
    Figure,
    Heading,
    Legend,
    Marker,
    Notice,
    Paragraph,
    Table,
)
from .camera_planner import PlannedView, project
from .design_check import DesignCheck, design_check, parse_required
from .hotspots import Hotspot
from .i18n import Translator
from .models import (
    ConstraintKind,
    FemResult,
    FieldKind,
    ReportConfig,
    ReportLevel,
    ResultField,
    Vec3,
)
from .hotspots import HotspotKind
from .quality import (EquilibriumCheck, EquilibriumStatus, ErrorEstimate, MeshQuality,
                      relative_change, volume_above)
from .colors import LOAD_RGB, SUPPORT_RGB
from .templates import accent_rgb
from .trace import Traceability
from .sections import ALL_LEVELS, DETAILED_LEVELS, Section, SectionRegistry, compose
from .units import Quantity, format_number_like, pretty_unit

Report = Document  # former name, kept for callers


# --- inputs ------------------------------------------------------------------

@dataclass
class ReportInputs:
    result: FemResult
    config: ReportConfig
    hotspots: list[Hotspot]
    views: list[PlannedView]
    image_size: tuple[int, int]
    document_name: str
    date: datetime.date
    yield_strength: Quantity | None = None
    yield_source: str = ""  # "user" or "material"
    max_on_surface: bool | None = None  # None = unknown (no surface)
    surface_available: bool = True
    tool_version: str = ""
    freecad_version: str = ""
    # Step f (decisions 004 and 005); None = not computed
    equilibrium: EquilibriumCheck | None = None
    mesh_quality: MeshQuality | None = None
    error_estimate: ErrorEstimate | None = None
    error_field: ResultField | None = None  # nodal ZZ indicator in %
    error_view: PlannedView | None = None  # its image is the one after the views
    # Supports and loads on a gray part; their images come FIRST (figure 1...).
    boundary_views: list = field(default_factory=list)
    # Distance from supports/loads beyond which stress counts as "regular"
    # (the STRESS_REGULAR hotspot); None when not computed.
    regular_exclusion: Quantity | None = None
    # Largest principal stress away from supports, loads and sharp corners (same
    # rule as STRESS_REGULAR); None when unknown. Rankine design value of polymers.
    regular_principal: Quantity | None = None
    # Reaction force of each support from CalculiX: [(support label, Vec3 in N)].
    reactions: list = field(default_factory=list)
    # Passes of "Optimise mesh by the error" that produced this mesh (quality.ConvergencePass).
    convergence: list = field(default_factory=list)
    trace: Traceability | None = None  # step e

    def field(self, kind: FieldKind) -> ResultField | None:
        if kind is FieldKind.ESTIMATED_ERROR:
            return self.error_field
        return self.result.get_field(kind)


# Views per report level (owner's request): the quick summary shows the two
# overviews only; FULL uses the configured maximum.
LEVEL_VIEW_LIMIT = {ReportLevel.QUICK: 2, ReportLevel.STANDARD: 4, ReportLevel.FULL: None}


def views_for_level(config: ReportConfig) -> int:
    limit = LEVEL_VIEW_LIMIT[config.level]
    return config.max_views if limit is None else min(limit, config.max_views)


def result_digits(inputs) -> int:
    """Significant digits of computed results, tied to the estimated error:
    2 + floor(-log10(error)), between 2 and 4 (error 20 % -> 2, 5 % -> 3,
    0,5 % -> 4). Printing 0,8908 MPa from a model with 20 % error suggests a
    precision that does not exist. Unknown error: 3."""
    zz = getattr(inputs, "error_estimate", None)
    if zz is None or not zz.available or zz.relative_error <= 0:
        return 3
    return max(2, min(4, 2 + int(math.floor(-math.log10(zz.relative_error)))))


def safety_factor(yield_strength: Quantity, max_stress: Quantity) -> float:
    if yield_strength.unit != max_stress.unit:
        raise ValueError("units differ: %s vs %s" % (yield_strength.unit, max_stress.unit))
    if max_stress.value <= 0:
        raise ValueError("maximum stress must be positive")
    return yield_strength.value / max_stress.value


def order_hotspots(hotspots) -> list[Hotspot]:
    """Report numbering order: by priority, then by peak value (highest first)."""
    return sorted(hotspots, key=lambda h: (h.priority,
                                           -(h.peak_value.value if h.peak_value else 0.0)))


# --- builder -----------------------------------------------------------------

def hotspot_name(spot: Hotspot, tr: Translator) -> str:
    name = tr.t("hotspot." + spot.kind.value)
    return "%s: %s" % (name, spot.label) if spot.label else name


def _field_name(kind: FieldKind, tr: Translator) -> str:
    return tr.t("field." + kind.value)


def _clean(v: Vec3, eps: float = 1e-9) -> Vec3:
    """Drop floating-point noise such as 4.1e-16 in unit directions."""
    return Vec3(*(0.0 if abs(c) < eps else c for c in v))


def _summary(inputs: ReportInputs, tr: Translator) -> Table:
    res = inputs.result
    rows = [(tr.t("summary.solver"), res.solver or "—")]
    analysis = ("analysis." + res.analysis_type) if res.analysis_type else ""
    rows.append((tr.t("summary.analysis"),
                 tr.t(analysis) if analysis and tr.has(analysis) else res.analysis_type or "—"))
    for mat in res.materials:
        rows.append((tr.t("summary.material"), tr.t(
            "summary.material_text", name=mat.name, e=tr.quantity(mat.youngs_modulus, 4),
            nu=tr.number(mat.poisson_ratio, 2) if mat.poisson_ratio is not None else "—",
            rho=tr.quantity(mat.density, 4))))
    m = res.mesh
    rows.append((tr.t("summary.mesh"), tr.t(
        "summary.mesh_text", nodes=m.node_count, elements=m.element_count,
        order=tr.t("summary.order.%d" % m.element_order))))
    supports, loads = [], []
    for c in res.constraints:
        refs = tr.t("summary.on", refs=tr.list_sep.join(c.references)) if c.references else ""
        if c.kind in (ConstraintKind.FIXED, ConstraintKind.DISPLACEMENT):
            supports.append(" ".join(p for p in (c.label, refs) if p))
        else:
            direction = tr.point(_clean(c.direction), "", 2).strip() if c.direction else "—"
            text = tr.t("summary.load_text", label=c.label, magnitude=tr.quantity(c.magnitude, 4),
                        direction=direction)
            loads.append(" ".join(p for p in (text, refs) if p))
    rows.append((tr.t("summary.supports"), "\n".join(supports) or tr.t("summary.none")))
    rows.append((tr.t("summary.loads"), "\n".join(loads) or tr.t("summary.none")))
    return Table(header=(), rows=tuple(rows), widths=(0.25, 0.75))


def _results(inputs: ReportInputs, tr: Translator) -> Table:
    res, m = inputs.result, inputs.result.mesh
    d = result_digits(inputs)
    rows = []
    regular = next((h for h in inputs.hotspots if h.kind is HotspotKind.STRESS_REGULAR), None)
    for kind, max_key, min_key in ((FieldKind.VON_MISES, "results.vm_max", "results.vm_min"),
                                   (FieldKind.DISPLACEMENT, "results.disp_max", "results.disp_min")):
        f = res.get_field(kind)
        if f is None:
            continue
        for key, nv in ((max_key, f.maximum(m)), (min_key, f.minimum(m))):
            rows.append((tr.t(key), tr.quantity(nv.value, d), tr.point(nv.position, m.length_unit),
                         str(nv.node_id)))
            if key == "results.vm_min":
                p = res.get_field(FieldKind.PRINCIPAL_MAX)
                if p is not None:
                    nv1 = p.maximum(m)
                    rows.append((tr.t("results.principal_max"), tr.quantity(nv1.value, d),
                                 tr.point(nv1.position, m.length_unit), str(nv1.node_id)))
            if key == "results.vm_max" and regular is not None:
                rows.append((tr.t("results.vm_regular"), tr.quantity(regular.peak_value, d),
                             tr.point(regular.center, m.length_unit), str(regular.peak_node)))
    header = (tr.t("results.quantity"), tr.t("results.value"), tr.t("results.location"),
              tr.t("results.node"))
    return Table(header=header, rows=tuple(rows), widths=(0.36, 0.2, 0.32, 0.12))


def _share(tr: Translator, value: float) -> str:
    """Share of the volume in %, readable when tiny (never a misleading 0 %)."""
    if value <= 0:
        return "0 %"
    if value < 0.0001:
        return "< 0,01 %" if tr.decimal_sep == "," else "< 0.01 %"
    return tr.number(100 * value, 2) + " %"


def _reactions(reactions, tr: Translator) -> Table:
    """Force each support takes (what bolts and fixtures must hold)."""
    rows = []
    for label, f in reactions:
        rows.append((label,) + tuple(tr.quantity(Quantity(v, "N"), 3) for v in _clean(f))
                    + (tr.quantity(Quantity(g.length(f), "N"), 3),))
    header = (tr.t("reactions.support"), "Fx", "Fy", "Fz", "|F|")
    return Table(header=header, rows=tuple(rows), widths=(0.32, 0.17, 0.17, 0.17, 0.17))


def _points(hotspots, tr: Translator, length_unit: str, figures, digits: int = 4,
            local_error=None) -> Table:
    """Points table; the numbers are the balloons drawn on the figures.

    ``local_error``: {node: estimated local error in %} (ZZ): each value comes
    with its own confidence, not only the global one."""
    shown_in = {}
    for fig in figures:
        for m in fig.markers:
            shown_in.setdefault(m.number, []).append(str(fig.view_index + 1))
    # The "Alert" column only exists when at least one point has an alert.
    with_alerts = any(spot.singularity_near or spot.sharp_corner for spot in hotspots)
    rows = []
    for n, spot in enumerate(hotspots, start=1):
        row = (str(n), hotspot_name(spot, tr), tr.quantity(spot.peak_value, digits),
               tr.point(spot.center, length_unit),
               tr.list_sep.join(shown_in.get(n, [])) or "—")
        if local_error:
            e = local_error.get(spot.peak_node)
            row += (tr.number(e, 2) + " %" if e is not None else "—",)
        if with_alerts:
            row += (tr.t("points.singularity", label=spot.singularity_near)
                    if spot.singularity_near
                    else tr.t("points.sharp_corner") if spot.sharp_corner else "",)
        rows.append(row)
    header = (tr.t("points.number"), tr.t("points.type"), tr.t("points.value"),
              tr.t("points.location"), tr.t("points.figures"))
    if local_error:
        header += (tr.t("points.local_error"),)
    if with_alerts:
        header += (tr.t("points.alert"),)
    widths = {(False, False): (0.07, 0.31, 0.2, 0.29, 0.13),
              (True, False): (0.06, 0.27, 0.15, 0.25, 0.11, 0.16),
              (False, True): (0.06, 0.25, 0.16, 0.25, 0.1, 0.18),
              (True, True): (0.05, 0.2, 0.12, 0.21, 0.1, 0.11, 0.21)}[
                  (bool(local_error), with_alerts)]
    return Table(header=header, rows=tuple(rows), widths=tuple(widths))


def _balloon_text(spot: Hotspot, number: int, tr: Translator, digits: int = 4) -> str:
    name = hotspot_name(spot, tr)
    if spot.peak_value is not None:
        name = "%s (%s)" % (name, tr.quantity(spot.peak_value, digits))
    return "%d = %s" % (number, name)


def _legend(inputs: ReportInputs, kind: FieldKind, tr: Translator) -> Legend:
    f = inputs.field(kind)
    vmin, vmax = min(f.values), max(f.values)
    ticks = colormap.tick_values(vmin, vmax, 5)
    reference = max(abs(vmin), abs(vmax))
    labels = tuple((i / 4.0, format_number_like(v, reference, 3, tr.decimal_sep))
                   for i, v in enumerate(ticks))
    return Legend(title="%s [%s]" % (_field_name(kind, tr), pretty_unit(f.unit)), ticks=labels)


def _markers(view: PlannedView, inputs: ReportInputs, numbers):
    """Balloons of one view (each spot once) and the spots that got one."""
    w, h = inputs.image_size
    markers, shown = [], []
    leaders = dict(zip(view.targets, view.leaders)) if view.leaders else {}
    for spot in sorted(dict.fromkeys(view.targets), key=numbers.__getitem__):  # each spot once
        points = leaders.get(spot, spot.leader_points)
        pixels = [project(view.camera, p, w, h) for p in points]
        pixels = [(u, v) for u, v in pixels if 0 <= u <= w and 0 <= v <= h]
        if pixels:
            style = {HotspotKind.LOAD: "load", HotspotKind.SUPPORT: "support"}.get(
                spot.kind, "result")
            markers.append(Marker(numbers[spot], pixels[0][0], pixels[0][1], style,
                                  tuple(pixels[1:])))
            shown.append(spot)
    return markers, shown


def _figure(index, view: PlannedView, inputs: ReportInputs, numbers, tr: Translator) -> Figure:
    if view.color_field is None:
        return _boundary_figure(index, view, inputs, numbers, tr)
    markers, shown = _markers(view, inputs, numbers)
    field_name = _field_name(view.color_field, tr)
    key = "fig.overview" if view.is_overview else "fig.closeup"
    text = tr.t(key, field=field_name)
    if view.deformation:
        text = tr.t("fig.deformed", field=field_name, scale=tr.integer(view.deformation))
    caption = tr.t("fig.caption", n=index + 1, text=text)
    balloons = ""
    if shown:
        balloons = tr.t("fig.marker_list", items=tr.list_sep.join(
            _balloon_text(s, numbers[s], tr, result_digits(inputs)) for s in shown))
        if any(m.style != "result" for m in markers):
            balloons += " " + tr.t("fig.marker_colors")
    return Figure(view_index=index, caption=caption,
                  legend=_legend(inputs, view.color_field, tr), markers=tuple(markers),
                  image_size=inputs.image_size, balloons=balloons)


def _constraint_text(c, tr: Translator) -> str:
    if c.magnitude is not None:
        return "%s (%s)" % (c.label, tr.quantity(c.magnitude, 4))
    return c.label


def _boundary_figure(index, view: PlannedView, inputs: ReportInputs, numbers,
                     tr: Translator) -> Figure:
    """Supports (purple) and loads (orange) on the gray part: colors only.

    No balloons (owner's request): the caption names what is visible in this view.
    """
    seen = {t.label for t in view.targets}
    supports, loads = [], []
    for c in inputs.result.constraints:
        if c.label not in seen:
            continue
        if c.kind in (ConstraintKind.FIXED, ConstraintKind.DISPLACEMENT):
            supports.append(_constraint_text(c, tr))
        elif c.kind in (ConstraintKind.FORCE, ConstraintKind.PRESSURE):
            loads.append(_constraint_text(c, tr))
    parts = []
    if supports:
        parts.append(tr.t("fig.boundary_supports", items=tr.list_sep.join(supports)))
    if loads:
        parts.append(tr.t("fig.boundary_loads", items=tr.list_sep.join(loads)))
    legend = Legend(title=tr.t("fig.boundary_legend"), ticks=(),
                    swatches=((SUPPORT_RGB, tr.t("summary.supports")),
                              (LOAD_RGB, tr.t("summary.loads"))))
    return Figure(view_index=index,
                  caption=tr.t("fig.caption", n=index + 1, text=tr.t("fig.boundary")),
                  legend=legend, markers=(), image_size=inputs.image_size,
                  balloons=" ".join(parts))


@dataclass
class FemContext:
    """Data shared by the FEM sections, computed once per report."""

    inputs: ReportInputs
    numbers: dict  # hotspot -> balloon number
    figures: list
    check: DesignCheck | None = None  # design safety factor (None: no material limit)


def prepare_fem(inputs: ReportInputs, tr: Translator) -> FemContext:
    hotspots = list(inputs.hotspots)
    numbers = {spot: n for n, spot in enumerate(hotspots, start=1)}
    figures = [_figure(index, view, inputs, numbers, tr)  # capture order = figure order
               for index, view in enumerate(list(inputs.boundary_views) + list(inputs.views))]
    figures = _note_hidden(figures, inputs, numbers, tr)
    return FemContext(inputs, numbers, figures, _design_check(inputs))


def _design_check(inputs: ReportInputs) -> DesignCheck | None:
    res = inputs.result
    stress = res.get_field(FieldKind.VON_MISES)
    if stress is None or inputs.yield_strength is None:
        return None
    peak = stress.maximum(res.mesh).value
    regular = next((h for h in inputs.hotspots if h.kind is HotspotKind.STRESS_REGULAR), None)
    smax = next((h for h in inputs.hotspots if h.kind is HotspotKind.STRESS_MAX), None)
    if regular is not None:
        design = regular.peak_value
    elif smax is not None and not (smax.singularity_near or smax.sharp_corner):
        design = peak  # the maximum itself is away from supports, loads and corners
    else:
        design = None  # unknown: the peak is used (safe side)
    principal = res.get_field(FieldKind.PRINCIPAL_MAX)
    mat = _material(inputs)
    try:
        required = parse_required(inputs.config.required_safety)
    except ValueError:
        required = None  # the dialog refuses it; a script may still pass it
    return design_check(inputs.yield_strength, inputs.yield_source, design, peak,
                        family=mat.family if mat is not None else "other",
                        ultimate=mat.ultimate_strength if mat is not None else None,
                        s1_design=inputs.regular_principal,
                        s1_peak=principal.maximum(res.mesh).value if principal else None,
                        required=required)


def _material(inputs: ReportInputs):
    return inputs.result.materials[0] if len(inputs.result.materials) == 1 else None


def _criterion_name(c, tr: Translator) -> str:
    return tr.t("check.crit." + c.key)


def _where_design(c, tr: Translator) -> str:
    return tr.t("check.where_regular" if c.design_is_regular else "check.where_peak")


def _criteria_table(check: DesignCheck, tr: Translator, d: int) -> Table:
    """Each criterion: limit, design stress and peak stress with their factors."""
    rows = []
    for c in check.criteria:
        name = _criterion_name(c, tr)
        if c is check.governing and len(check.criteria) > 1:
            name += " — " + tr.t("check.governs")
        limit = tr.quantity(c.limit, 4)
        if c.limit_source:
            limit += " (%s)" % tr.t("results.yield_source." + c.limit_source)
        design = tr.quantity(c.design_stress, d)
        if not c.design_is_regular:
            design += " (%s)" % tr.t("check.where_peak")
        rows.append((name, limit, design, tr.number(c.fs_design, d),
                     tr.quantity(c.peak_stress, d), tr.number(c.fs_peak, d)))
    header = tuple(tr.t("check.col." + k) for k in
                   ("criterion", "limit", "design", "fs_design", "peak", "fs_peak"))
    return Table(header=header, rows=tuple(rows), widths=(0.22, 0.2, 0.17, 0.12, 0.17, 0.12))


def _conclusion(ctx: FemContext, tr: Translator) -> Notice | None:
    """The verdict in one block, first thing in the report."""
    check = ctx.check
    if check is None:
        if ctx.inputs.result.get_field(FieldKind.VON_MISES) is None:
            return None
        return Notice(tr.t("check.none"), level="info")
    d = result_digits(ctx.inputs)
    c = check.governing
    values = dict(fs=tr.number(check.fs, d), criterion=_criterion_name(c, tr),
                  where=_where_design(c, tr),
                  required=tr.number(check.required, 3) if check.required else "")
    level = {"meets": "ok", "fails": "warning", "exceeds": "warning", "number": "info"}
    return Notice(tr.t("check." + check.status, **values), level=level[check.status])


def _note_hidden(figures, inputs: ReportInputs, numbers, tr: Translator) -> list:
    """Overviews say which points of their field they could not show, and where
    they are: a reader must never take the balloons of one view for the worst
    points of the part."""
    views = list(inputs.boundary_views) + list(inputs.views)
    shown_in = {}
    for fig in figures:
        for m in fig.markers:
            shown_in.setdefault(m.number, []).append(str(fig.view_index + 1))
    out = []
    for fig, view in zip(figures, views):
        if view.is_overview and view.color_field is not None:
            drawn = {m.number for m in fig.markers}
            hidden = [numbers[h] for h in inputs.hotspots
                      if h.color_field is view.color_field and numbers[h] not in drawn]
            if hidden:
                items = tr.list_sep.join(
                    "%d (%s)" % (n, tr.t("fig.see", figures=", ".join(shown_in[n])))
                    if n in shown_in else str(n) for n in sorted(hidden))
                note = tr.t("fig.hidden", items=items)
                fig = replace(fig, balloons=(fig.balloons + " " + note).strip())
        out.append(fig)
    return out


def _section_views(ctx: FemContext, tr: Translator, level) -> list:
    return list(ctx.figures)


def _section_summary(ctx: FemContext, tr: Translator, level) -> list:
    return [_summary(ctx.inputs, tr)]


def _section_results(ctx: FemContext, tr: Translator, level) -> list:
    inputs, check = ctx.inputs, ctx.check
    res = inputs.result
    stress = res.get_field(FieldKind.VON_MISES)
    blocks = [_results(inputs, tr)]
    if check is not None:
        blocks.append(Paragraph(tr.t("check.intro")))
        blocks.append(_criteria_table(check, tr, result_digits(inputs)))
    detailed = level is not ReportLevel.QUICK  # the quick summary keeps the main table
    mat = _material(inputs)
    if inputs.yield_source == "user" and mat is not None and mat.ultimate_strength is not None \
            and inputs.yield_strength is not None \
            and mat.ultimate_strength.unit == inputs.yield_strength.unit \
            and inputs.yield_strength.value > mat.ultimate_strength.value:
        blocks.append(Notice(tr.t("warn.yield_above_uts",
                                  limit=tr.quantity(inputs.yield_strength, 4),
                                  uts=tr.quantity(mat.ultimate_strength, 4))))
    if inputs.reactions and detailed:
        blocks.append(Paragraph(tr.t("reactions.intro")))
        blocks.append(_reactions(inputs.reactions, tr))
        eq = inputs.equilibrium
        if eq is not None and eq.load_on_supports is not None \
                and g.length(eq.load_on_supports) > 1e-9 * max(g.length(eq.applied), 1e-30):
            blocks.append(Notice(tr.t("reactions.load_on_supports"), level="info"))
    if detailed and inputs.yield_strength is not None and stress is not None and res.elements \
            and stress.unit == inputs.yield_strength.unit:
        shares = volume_above(res.elements, res.mesh.node_positions,
                              dict(zip(stress.node_ids, stress.values)),
                              inputs.yield_strength.value)
        if shares and shares[0][1] == 0:  # nothing reaches the first fraction: one sentence
            blocks.append(Paragraph(tr.t("volume.none", pct=tr.integer(100 * shares[0][0]),
                                         limit=tr.quantity(Quantity(
                                             shares[0][0] * inputs.yield_strength.value,
                                             inputs.yield_strength.unit), 3))))
        elif shares:
            rows = tuple((tr.t("volume.row", pct=tr.integer(100 * f),
                               limit=tr.quantity(Quantity(f * inputs.yield_strength.value,
                                                          inputs.yield_strength.unit), 3)),
                          _share(tr, v)) for f, v in shares)
            blocks.append(Paragraph(tr.t("volume.intro")))
            blocks.append(Table(header=(tr.t("volume.stress"), tr.t("volume.share")),
                                rows=rows, widths=(0.6, 0.4)))
    if check is None and stress is not None:
        blocks.append(Notice(tr.t("warn.no_yield"), level="info"))
    if inputs.max_on_surface is False and stress is not None:
        blocks.append(Notice(tr.t("warn.max_inside", node=stress.maximum(res.mesh).node_id),
                             level="info"))
    if not inputs.surface_available:
        blocks.append(Notice(tr.t("warn.no_surface"), level="info"))
    return blocks


def _section_points(ctx: FemContext, tr: Translator, level) -> list:
    hotspots = list(ctx.inputs.hotspots)
    if not hotspots:
        return []
    inputs = ctx.inputs
    local = None
    if inputs.error_field is not None:
        local = dict(zip(inputs.error_field.node_ids, inputs.error_field.values))
    blocks = [Paragraph(tr.t("points.intro") + " " + tr.t("points.criteria")),
              _points(hotspots, tr, inputs.result.mesh.length_unit, ctx.figures,
                      result_digits(inputs), local)]
    for c in ctx.inputs.result.constraints:
        if c.on_edges_or_vertices and c.kind in (ConstraintKind.FIXED, ConstraintKind.FORCE):
            blocks.append(Notice(tr.t("warn.line_constraint", label=c.label)))
    # One notice per support/load (not one per point), then the sharp corners.
    by_label = {}
    for n, spot in enumerate(hotspots, start=1):
        if spot.singularity_near:
            by_label.setdefault(spot.singularity_near, []).append(str(n))
    for label, ns in by_label.items():
        key = "warn.singularity" if len(ns) == 1 else "warn.singularity_many"
        blocks.append(Notice(tr.t(key, n=tr.list_sep.join(ns), label=label)))
    corners = [str(n) for n, spot in enumerate(hotspots, start=1) if spot.sharp_corner]
    if corners:
        key = "warn.sharp_corner" if len(corners) == 1 else "warn.sharp_corner_many"
        blocks.append(Notice(tr.t(key, n=tr.list_sep.join(corners))))
    return blocks


def _figures_of(ctx: FemContext, spot: Hotspot) -> list:
    number = ctx.numbers.get(spot)
    return [str(f.view_index + 1) for f in ctx.figures
            if any(m.number == number for m in f.markers)]


def _first(ctx: FemContext, kind: HotspotKind) -> Hotspot | None:
    return next((h for h in ctx.inputs.hotspots if h.kind is kind), None)


def _where(ctx: FemContext, tr: Translator, spot: Hotspot | None) -> str:
    if spot is None:
        return ""
    figs = _figures_of(ctx, spot)
    text = tr.t("exec.point", n=ctx.numbers[spot])
    if figs:
        key = "exec.figure" if len(figs) == 1 else "exec.figures"
        text += " " + tr.t(key, figures=tr.list_sep.join(figs))
    return text


def _alerts(ctx: FemContext) -> int:
    inputs = ctx.inputs
    count = sum(1 for h in inputs.hotspots if h.singularity_near or h.sharp_corner)
    count += sum(1 for c in inputs.result.constraints if c.on_edges_or_vertices)
    if ctx.check is not None and ctx.check.status in ("fails", "exceeds"):
        count += 1
    if inputs.equilibrium is not None and inputs.equilibrium.status is EquilibriumStatus.IMBALANCE:
        count += 1
    if inputs.mesh_quality is not None and inputs.mesh_quality.invalid_elements:
        count += 1
    return count


def _section_executive(ctx: FemContext, tr: Translator, level) -> list:
    """Plain-language verdict built only from the computed data (step c)."""
    inputs = ctx.inputs
    res = inputs.result
    stress = res.get_field(FieldKind.VON_MISES)
    disp = res.get_field(FieldKind.DISPLACEMENT)
    rows, sentences = [], []
    d = result_digits(inputs)
    smax = _first(ctx, HotspotKind.STRESS_MAX)
    if stress is not None:
        value = tr.quantity(stress.maximum(res.mesh).value, d)
        rows.append((tr.t("results.vm_max"), " ".join(p for p in (value, _where(ctx, tr, smax)) if p)))
    regular = _first(ctx, HotspotKind.STRESS_REGULAR)
    if regular is not None:
        value = tr.quantity(regular.peak_value, d)
        rows.append((tr.t("results.vm_regular"),
                     " ".join(p for p in (value, _where(ctx, tr, regular)) if p)))
    if disp is not None:
        dmax = _first(ctx, HotspotKind.DISPLACEMENT_MAX)
        value = tr.quantity(disp.maximum(res.mesh).value, d)
        rows.append((tr.t("results.disp_max"), " ".join(p for p in (value, _where(ctx, tr, dmax)) if p)))
    check = ctx.check
    peak_note = False  # the singular peak is already explained by exec.peak_fs
    if check is not None:
        c = check.governing
        rows.append((tr.t("exec.design_fs"), tr.t("exec.design_fs_value", fs=tr.number(check.fs, d),
                                                  criterion=_criterion_name(c, tr),
                                                  where=_where_design(c, tr))))
        if check.required is not None:
            rows.append((tr.t("exec.required_fs"), tr.number(check.required, 3)))
        if c.design_is_regular and c.fs_peak < c.fs_design and smax is not None \
                and (smax.singularity_near or smax.sharp_corner):
            sentences.append(tr.t("exec.peak_fs", n=ctx.numbers[smax], fs=tr.number(c.fs_peak, d),
                                  value=tr.quantity(c.peak_stress, d)))
            peak_note = True
    elif stress is not None:
        rows.append((tr.t("exec.design_fs"), tr.t("exec.safety_none")))
    if smax is not None and smax.singularity_near and not peak_note:
        sentences.append(tr.t("exec.singular", n=ctx.numbers[smax], label=smax.singularity_near))
    elif smax is not None and smax.sharp_corner:
        sentences.append(tr.t("exec.sharp_corner", n=ctx.numbers[smax]))
    if regular is not None and inputs.regular_exclusion is not None:
        sentences.append(tr.t("exec.regular", n=ctx.numbers[regular],
                              value=tr.quantity(regular.peak_value, d),
                              distance=tr.quantity(inputs.regular_exclusion, 2)))
    eq = inputs.equilibrium
    if eq is not None:
        rows.append((tr.t("quality.equilibrium"), tr.t("eq.status." + eq.status.value)))
        if eq.status is EquilibriumStatus.IMBALANCE:
            sentences.append(tr.t("exec.equilibrium", residual=tr.number(100 * eq.residual, 2)))
    zz = inputs.error_estimate
    if zz is not None and zz.available:
        rows.append((tr.t("quality.error"), tr.number(100 * zz.relative_error, 3) + " %"))
        key = "exec.error" if level is not ReportLevel.QUICK else "exec.error_quick"
        sentences.append(tr.t(key, eta=tr.number(100 * zz.relative_error, 3)))
    q = inputs.mesh_quality
    if q is not None and q.invalid_elements:
        sentences.append(tr.t("exec.invalid", n=q.invalid_elements))
    alerts = _alerts(ctx)
    rows.append((tr.t("exec.alerts"), str(alerts) if alerts else tr.t("exec.alerts_none")))
    blocks = [Table(header=(), rows=tuple(rows), widths=(0.36, 0.64))]
    conclusion = _conclusion(ctx, tr)
    if conclusion is not None:
        blocks.insert(0, conclusion)
    if inputs.config.intro_text:
        blocks.insert(0, Paragraph(inputs.config.intro_text))  # user text, never translated
    if sentences:
        blocks.append(BulletList(tuple(sentences)))
    return blocks


def _section_glossary(ctx: FemContext, tr: Translator, level) -> list:
    """One line per harder concept, only those this report uses: read once,
    then out of the way of the daily reader."""
    inputs, check = ctx.inputs, ctx.check
    res = inputs.result
    terms = []
    if check is not None:
        terms += ["design_fs", "design_stress"]
        if check.required is not None:
            terms.append("required_fs")
    if any(h.singularity_near or h.sharp_corner for h in inputs.hotspots):
        terms.append("singularity")
    if res.get_field(FieldKind.VON_MISES) is not None:
        terms.append("von_mises")
    if check is not None and any(c.key == "rankine" for c in check.criteria):
        terms.append("rankine")
    if inputs.error_estimate is not None and inputs.error_estimate.available:
        terms.append("error")
    if inputs.equilibrium is not None:
        terms.append("equilibrium")
    if any(v.deformation for v in inputs.views):
        terms.append("deformed")
    if not terms:
        return []
    rows = tuple((tr.t("glossary.%s" % k), tr.t("glossary.%s.text" % k)) for k in terms)
    return [Table(header=(), rows=rows, widths=(0.26, 0.74))]


def _section_assumptions(ctx: FemContext, tr: Translator, level) -> list:
    """What the analysis assumes and what the report does not assess (step d)."""
    inputs = ctx.inputs
    res = inputs.result
    system = inputs.config.unit_system.value
    units = Paragraph(tr.t("note.units", system=tr.t("note.units." + system)))
    if level is ReportLevel.QUICK:
        blocks = [Paragraph(tr.t("assume.short"))]
        mat = _material(inputs)
        if mat is not None and mat.family == "polymer":
            blocks.append(Paragraph(tr.t("assume.short_polymer")))
        if inputs.yield_source == "material_uts":
            blocks.append(Paragraph(tr.t("assume.uts_used")))
        return blocks + [units]
    trace = inputs.trace
    assumed = []
    if res.analysis_type == "static":
        assumed.append(tr.t("assume.static"))
    if trace is not None and trace.setting("GeometricalNonlinearity") == "linear":
        assumed.append(tr.t("assume.small_displacements"))
    if trace is None or trace.setting("MaterialNonlinearity") in ("linear", ""):
        for mat in res.materials:
            assumed.append(tr.t("assume.linear_material", name=mat.name,
                                e=tr.quantity(mat.youngs_modulus, 4),
                                nu=tr.number(mat.poisson_ratio, 2)
                                if mat.poisson_ratio is not None else "—"))
    mat = _material(inputs)
    if mat is not None and mat.family == "metal":
        assumed.append(tr.t("assume.criterion_metal"))
    elif mat is not None and mat.family == "polymer":
        assumed.append(tr.t("assume.criterion_polymer"))
        assumed.append(tr.t("assume.printed"))
        assumed.append(tr.t("assume.polymer_time"))
    if inputs.yield_source == "material_uts":
        assumed.append(tr.t("assume.uts_used"))
    if any(c.kind is ConstraintKind.FIXED for c in res.constraints):
        assumed.append(tr.t("assume.fixed"))
    if any(c.kind is ConstraintKind.FORCE for c in res.constraints):
        assumed.append(tr.t("assume.force"))
    blocks = [Paragraph(tr.t("assume.intro")), BulletList(tuple(assumed))]
    not_assessed = [tr.t("assume.not." + k) for k in
                    ("fatigue", "buckling", "contact", "plasticity", "dynamics", "thermal",
                     "manufacturing", "boundary")]
    blocks += [Paragraph(tr.t("assume.not_intro")), BulletList(tuple(not_assessed))]
    dependence = [tr.t("assume.mesh")]
    singular = sum(1 for h in inputs.hotspots if h.singularity_near or h.sharp_corner)
    if singular:
        dependence.append(tr.t("assume.singular", n=singular))
    if inputs.regular_exclusion is not None:
        dependence.append(tr.t("assume.regular",
                               distance=tr.quantity(inputs.regular_exclusion, 2)))
    dependence.append(tr.t("assume.digits", n=result_digits(inputs)))
    dependence.append(tr.t("assume.surface"))
    blocks.append(BulletList(tuple(dependence)))
    if inputs.config.disclaimer_text:
        blocks.append(Paragraph(inputs.config.disclaimer_text))  # user text
    blocks.append(units)
    return blocks


def _section_trace(ctx: FemContext, tr: Translator, level) -> list:
    t = ctx.inputs.trace
    if t is None:
        return []
    when = t.generated_at.strftime("%d/%m/%Y %H:%M" if tr.language == "pt_BR" else "%Y-%m-%d %H:%M")
    rows = [
        (tr.t("trace.tool"), "PartReview %s" % t.tool_version),
        (tr.t("trace.freecad"), t.freecad_version),
        (tr.t("trace.generated"), when),
        (tr.t("trace.platform"), "%s · Python %s" % (t.platform, t.python_version)),
        (tr.t("trace.file"), t.file_path or t.file_name),
        (tr.t("trace.sha256"), t.file_sha256 or tr.t("trace.unsaved_never")),
    ]
    if t.file_modified is not None:
        rows.append((tr.t("trace.modified"), t.file_modified.strftime(
            "%d/%m/%Y %H:%M" if tr.language == "pt_BR" else "%Y-%m-%d %H:%M")))
    rows.append((tr.t("trace.result"), "%s (%s)" % (t.result_label, t.result_name)))
    rows.append((tr.t("trace.solver"), "%s · %s" % (t.solver, t.analysis_type)))
    if t.solver_settings:
        rows.append((tr.t("trace.solver_settings"),
                     tr.list_sep.join("%s = %s" % kv for kv in t.solver_settings)))
    if t.mesher:
        rows.append((tr.t("trace.mesher"), t.mesher))
    if t.mesher_settings:
        rows.append((tr.t("trace.mesher_settings"),
                     tr.list_sep.join("%s = %s" % kv for kv in t.mesher_settings)))
    config = ctx.inputs.config
    rows.append((tr.t("trace.report"), tr.t(
        "trace.report_value", language=config.language, units=tr.t("note.units." + config.unit_system.value))))
    blocks = [Table(header=(), rows=tuple(rows), widths=(0.3, 0.7))]
    if t.unsaved_changes:
        blocks.append(Notice(tr.t("warn.unsaved")))
    return blocks


def _vector(tr: Translator, v: Vec3, unit: str) -> str:
    return tr.point(_clean(v, 1e-6 * max(1.0, max(abs(c) for c in v))), unit, 4)


def _equilibrium_rows(eq: EquilibriumCheck, tr: Translator):
    status = tr.t("eq.status." + eq.status.value)
    if eq.status in (EquilibriumStatus.VERIFIED, EquilibriumStatus.IMBALANCE):
        detail = tr.t("eq.detail", applied=_vector(tr, eq.applied, "N"),
                      reactions=_vector(tr, eq.reactions, "N"),
                      residual=tr.number(100 * eq.residual, 2) + " %")
        on_supports = eq.load_on_supports
        if on_supports is not None and g.length(on_supports) > 1e-9 * g.length(eq.applied):
            detail += "\n" + tr.t("eq.detail_supports", load=_vector(tr, on_supports, "N"),
                                   share=tr.number(100 * g.length(on_supports)
                                                   / g.length(eq.applied), 3) + " %")
        return [(tr.t("quality.equilibrium"), "%s\n%s" % (status, detail))]
    return [(tr.t("quality.equilibrium"), "%s: %s" % (status, tr.t(eq.reason_key)))]


def _section_quality(ctx: FemContext, tr: Translator, level) -> list:
    inputs = ctx.inputs
    q, eq, zz = inputs.mesh_quality, inputs.equilibrium, inputs.error_estimate
    if q is None and eq is None and zz is None:
        return []
    detailed = level is not ReportLevel.QUICK
    rows = []
    if q is not None and detailed:
        rows.append((tr.t("quality.element"), tr.t("quality.element.%d" % q.nodes_per_element)
                     if tr.has("quality.element.%d" % q.nodes_per_element)
                     else str(q.nodes_per_element)))
    if q is not None:
        invalid = max(q.invalid_elements, zz.invalid_jacobian if zz and zz.available else 0)
        rows.append((tr.t("quality.invalid"), str(invalid)))
    if q is not None and detailed:
        rows.append((tr.t("quality.shape"), tr.t(
            "quality.shape_values", min=tr.number(q.ratio_min, 2), p5=tr.number(q.ratio_p5, 2),
            median=tr.number(q.ratio_median, 2))))
        unit = inputs.result.mesh.length_unit
        size = tr.t("quality.size_values", mean=tr.number(q.mean_edge, 3), unit=unit)
        if q.edge_at_max is not None:
            size += tr.list_sep + tr.t("quality.size_at_max", size=tr.number(q.edge_at_max, 3),
                                        unit=unit)
        rows.append((tr.t("quality.size"), size))
    if eq is not None:
        rows.extend(_equilibrium_rows(eq, tr))
    if zz is not None:
        value = (tr.number(100 * zz.relative_error, 3) + " %" if zz.available
                 else "%s: %s" % (tr.t("quality.not_available"), tr.t(zz.reason_key)))
        rows.append((tr.t("quality.error"), value))
    blocks = [Table(header=(), rows=tuple(rows), widths=(0.36, 0.64))]

    if eq is not None and eq.status is EquilibriumStatus.IMBALANCE:
        blocks.append(Notice(tr.t("warn.equilibrium", residual=tr.number(100 * eq.residual, 2))))
    if q is not None and q.invalid_elements:
        blocks.append(Notice(tr.t("warn.invalid_elements", n=q.invalid_elements)))
    if q is not None and q.nodes_per_element == 4:
        blocks.append(Notice(tr.t("quality.tet4_note"), level="info"))
    if zz is not None and zz.available and detailed:
        blocks.append(Paragraph(tr.t("quality.zz_explain")))
        if inputs.error_view is not None and inputs.error_field is not None:
            blocks.append(_error_figure(ctx, tr))
    if inputs.convergence and detailed:
        blocks += _convergence(inputs.convergence, tr)
    if q is not None and level is ReportLevel.FULL:
        labels = tuple("%s–%s" % (tr.number(i / 10, 1), tr.number((i + 1) / 10, 1))
                       for i in range(10))
        blocks.append(BarChart(title=tr.t("quality.histogram"), labels=labels,
                               values=tuple(float(v) for v in q.histogram),
                               caption=tr.t("quality.histogram_caption"),
                               x_title=tr.t("quality.histogram_x"),
                               y_title=tr.t("quality.histogram_y")))
    return blocks


CONVERGED_CHANGE = 0.05  # practical rule: < 5 % change between the last two meshes


def _convergence(passes, tr: Translator) -> list:
    """Mesh convergence study recorded by the optimiser: each mesh, its error and
    results, and how much the results changed between the last two meshes."""
    rows = tuple((str(i), tr.integer(p.nodes), tr.number(100 * p.error, 3) + " %",
                  tr.number(100 * p.global_error, 3) + " %",
                  tr.quantity(Quantity(p.max_stress_regular, "MPa"), 3),
                  tr.quantity(Quantity(p.max_displacement, "mm"), 3))
                 for i, p in enumerate(passes))
    header = (tr.t("conv.pass"), tr.t("conv.nodes"), tr.t("conv.error"),
              tr.t("conv.global_error"), tr.t("conv.stress"), tr.t("conv.displacement"))
    blocks = [Paragraph(tr.t("conv.intro")),
              Table(header=header, rows=rows, widths=(0.1, 0.15, 0.17, 0.15, 0.22, 0.21))]
    if len(passes) >= 2:
        a, b = passes[-2], passes[-1]
        ds = relative_change(a.max_stress_regular, b.max_stress_regular)
        dd = relative_change(a.max_displacement, b.max_displacement)
        if ds is not None and dd is not None:
            converged = max(ds, dd) < CONVERGED_CHANGE
            blocks.append(Notice(tr.t("conv.converged" if converged else "conv.not_converged",
                                      stress=tr.number(100 * ds, 2),
                                      disp=tr.number(100 * dd, 2)),
                                 level="info" if converged else "warning"))
    else:
        blocks.append(Notice(tr.t("conv.single"), level="info"))
    return blocks


def _error_figure(ctx: FemContext, tr: Translator) -> Figure:
    inputs = ctx.inputs
    index = len(inputs.boundary_views) + len(inputs.views)  # captured after the views
    caption = tr.t("fig.caption", n=index + 1, text=tr.t("fig.error_map"))
    return Figure(view_index=index, caption=caption,
                  legend=_legend(inputs, FieldKind.ESTIMATED_ERROR, tr), markers=(),
                  image_size=inputs.image_size)


# Order chosen by the owner: images first, then the tables. Steps c) to f) of
# phase 6a add their sections here; DFM (phase 4) and combined risks (phase 5)
# will register theirs in their own modules.
FEM_SECTIONS = SectionRegistry([
    Section("fem.executive", 50, "section.executive", ALL_LEVELS, _section_executive),
    Section("fem.views", 100, "section.views", ALL_LEVELS, _section_views),
    Section("fem.summary", 200, "section.summary", ALL_LEVELS, _section_summary),
    Section("fem.results", 300, "section.results", ALL_LEVELS, _section_results),
    Section("fem.points", 400, "section.points", DETAILED_LEVELS, _section_points),
    Section("fem.quality", 450, "section.quality", ALL_LEVELS, _section_quality),
    Section("fem.glossary", 880, "section.glossary", ALL_LEVELS, _section_glossary),
    Section("fem.assumptions", 900, "section.assumptions", ALL_LEVELS, _section_assumptions),
    Section("fem.trace", 950, "section.trace", DETAILED_LEVELS, _section_trace),
])


def _cover(inputs: ReportInputs, tr: Translator) -> Cover:
    config = inputs.config
    default_title = tr.t("report.default_title")
    info = [(tr.t("report.document"), inputs.document_name),
            (tr.t("report.result"), inputs.result.label),
            (tr.t("report.date"), tr.date(inputs.date))]
    if config.author:
        info.append((tr.t("report.author"), config.author))
    return Cover(
        title=config.title or default_title,
        subtitle=default_title if config.title else "",
        info=tuple(info),
        company=config.company,
        logo_path=config.logo_path,
        full_page=config.level is not ReportLevel.QUICK,
    )


def _footer(inputs: ReportInputs, tr: Translator) -> str:
    # The file hash stays only in the Traceability section (owner's request).
    return tr.t("report.generated_by", version=inputs.tool_version,
                freecad=inputs.freecad_version)


def build_report(inputs: ReportInputs, tr: Translator,
                 registry: SectionRegistry = FEM_SECTIONS) -> Document:
    level = inputs.config.level
    blocks, toc = compose(prepare_fem(inputs, tr), tr, registry, level)
    cover = _cover(inputs, tr)
    return Document(
        cover=cover,
        blocks=tuple(blocks),
        toc=tuple(toc) if level is not ReportLevel.QUICK else (),
        toc_title=tr.t("report.toc"),
        header_text=cover.title,
        footer=_footer(inputs, tr),
        page_template=tr.t("report.page", page="{page}", pages="{pages}"),
        author=inputs.config.author,
        accent=accent_rgb(inputs.config.accent_color) or DEFAULT_ACCENT,
    )
