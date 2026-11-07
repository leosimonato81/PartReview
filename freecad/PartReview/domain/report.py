# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""FEM report content: the FEM sections registered in the section engine.

What to say lives here; how to draw it lives in the PDF/HTML renderers. All
tool texts come from the Translator; user texts (title, author, company,
labels) are copied as they are.
"""

import datetime
from dataclasses import dataclass

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
from .quality import EquilibriumCheck, EquilibriumStatus, ErrorEstimate, MeshQuality
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


def _results(inputs: ReportInputs, tr: Translator, fs: float | None) -> Table:
    res, m = inputs.result, inputs.result.mesh
    rows = []
    for kind, max_key, min_key in ((FieldKind.VON_MISES, "results.vm_max", "results.vm_min"),
                                   (FieldKind.DISPLACEMENT, "results.disp_max", "results.disp_min")):
        f = res.get_field(kind)
        if f is None:
            continue
        for key, nv in ((max_key, f.maximum(m)), (min_key, f.minimum(m))):
            rows.append((tr.t(key), tr.quantity(nv.value, 4), tr.point(nv.position, m.length_unit),
                         str(nv.node_id)))
    if inputs.yield_strength is not None:
        source = tr.t("results.yield_source." + inputs.yield_source) if inputs.yield_source else ""
        rows.append((tr.t("results.yield"), tr.quantity(inputs.yield_strength, 4), source, ""))
    if fs is not None:
        rows.append((tr.t("results.safety"), tr.number(fs, 3), "", ""))
    header = (tr.t("results.quantity"), tr.t("results.value"), tr.t("results.location"),
              tr.t("results.node"))
    return Table(header=header, rows=tuple(rows), widths=(0.36, 0.2, 0.32, 0.12))


def _points(hotspots, tr: Translator, length_unit: str, figures) -> Table:
    """Points table; the numbers are the balloons drawn on the figures."""
    shown_in = {}
    for fig in figures:
        for m in fig.markers:
            shown_in.setdefault(m.number, []).append(str(fig.view_index + 1))
    # The "Alert" column only exists when at least one point has an alert.
    with_alerts = any(spot.singularity_near for spot in hotspots)
    rows = []
    for n, spot in enumerate(hotspots, start=1):
        row = (str(n), hotspot_name(spot, tr), tr.quantity(spot.peak_value, 4),
               tr.point(spot.center, length_unit),
               tr.list_sep.join(shown_in.get(n, [])) or "—")
        if with_alerts:
            row += (tr.t("points.singularity", label=spot.singularity_near)
                    if spot.singularity_near else "",)
        rows.append(row)
    header = (tr.t("points.number"), tr.t("points.type"), tr.t("points.value"),
              tr.t("points.location"), tr.t("points.figures"))
    if with_alerts:
        header += (tr.t("points.alert"),)
        widths = (0.06, 0.25, 0.16, 0.25, 0.1, 0.18)
    else:
        widths = (0.07, 0.31, 0.2, 0.29, 0.13)
    return Table(header=header, rows=tuple(rows), widths=widths)


def _balloon_text(spot: Hotspot, number: int, tr: Translator) -> str:
    name = hotspot_name(spot, tr)
    if spot.peak_value is not None:
        name = "%s (%s)" % (name, tr.quantity(spot.peak_value, 4))
    return "%d = %s" % (number, name)


def _legend(inputs: ReportInputs, kind: FieldKind, tr: Translator) -> Legend:
    f = inputs.field(kind)
    vmin, vmax = min(f.values), max(f.values)
    ticks = colormap.tick_values(vmin, vmax, 5)
    reference = max(abs(vmin), abs(vmax))
    labels = tuple((i / 4.0, format_number_like(v, reference, 3, tr.decimal_sep))
                   for i, v in enumerate(ticks))
    return Legend(title="%s [%s]" % (_field_name(kind, tr), pretty_unit(f.unit)), ticks=labels)


def _figure(index, view: PlannedView, inputs: ReportInputs, numbers, tr: Translator) -> Figure:
    w, h = inputs.image_size
    markers, shown = [], []
    for spot in sorted(view.targets, key=numbers.__getitem__):
        u, v = project(view.camera, spot.center, w, h)
        if 0 <= u <= w and 0 <= v <= h:
            markers.append(Marker(numbers[spot], u, v))
            shown.append(spot)
    field_name = _field_name(view.color_field, tr)
    key = "fig.overview" if view.is_overview else "fig.closeup"
    caption = tr.t("fig.caption", n=index + 1, text=tr.t(key, field=field_name))
    balloons = ""
    if shown:
        balloons = tr.t("fig.marker_list", items=tr.list_sep.join(
            _balloon_text(s, numbers[s], tr) for s in shown))
    return Figure(view_index=index, caption=caption,
                  legend=_legend(inputs, view.color_field, tr), markers=tuple(markers),
                  image_size=inputs.image_size, balloons=balloons)


@dataclass
class FemContext:
    """Data shared by the FEM sections, computed once per report."""

    inputs: ReportInputs
    numbers: dict  # hotspot -> balloon number
    figures: list
    fs: float | None


def prepare_fem(inputs: ReportInputs, tr: Translator) -> FemContext:
    hotspots = list(inputs.hotspots)
    numbers = {spot: n for n, spot in enumerate(hotspots, start=1)}
    res = inputs.result
    stress = res.get_field(FieldKind.VON_MISES)
    fs = None
    if inputs.yield_strength is not None and stress is not None:
        fs = safety_factor(inputs.yield_strength, stress.maximum(res.mesh).value)
    figures = [_figure(index, view, inputs, numbers, tr)
               for index, view in enumerate(inputs.views)]
    return FemContext(inputs, numbers, figures, fs)


def _section_views(ctx: FemContext, tr: Translator, level) -> list:
    return list(ctx.figures)


def _section_summary(ctx: FemContext, tr: Translator, level) -> list:
    return [_summary(ctx.inputs, tr)]


def _section_results(ctx: FemContext, tr: Translator, level) -> list:
    inputs, fs = ctx.inputs, ctx.fs
    res = inputs.result
    stress = res.get_field(FieldKind.VON_MISES)
    blocks = [_results(inputs, tr, fs)]
    if fs is not None and fs < 1.0:
        blocks.append(Notice(tr.t("warn.safety_low", fs=tr.number(fs, 3))))
    if fs is None and stress is not None:
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
    blocks = [Paragraph(tr.t("points.intro")),
              _points(hotspots, tr, ctx.inputs.result.mesh.length_unit, ctx.figures)]
    for n, spot in enumerate(hotspots, start=1):
        if spot.singularity_near:
            blocks.append(Notice(tr.t("warn.singularity", n=n, label=spot.singularity_near)))
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
    count = sum(1 for h in inputs.hotspots if h.singularity_near)
    if ctx.fs is not None and ctx.fs < 1.0:
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
    smax = _first(ctx, HotspotKind.STRESS_MAX)
    if stress is not None:
        value = tr.quantity(stress.maximum(res.mesh).value, 4)
        rows.append((tr.t("results.vm_max"), " ".join(p for p in (value, _where(ctx, tr, smax)) if p)))
    if disp is not None:
        dmax = _first(ctx, HotspotKind.DISPLACEMENT_MAX)
        value = tr.quantity(disp.maximum(res.mesh).value, 4)
        rows.append((tr.t("results.disp_max"), " ".join(p for p in (value, _where(ctx, tr, dmax)) if p)))
    if ctx.fs is not None:
        source = tr.t("results.yield_source." + inputs.yield_source) if inputs.yield_source else ""
        rows.append((tr.t("exec.safety"), tr.t("exec.safety_value", fs=tr.number(ctx.fs, 3),
                                                 limit=tr.quantity(inputs.yield_strength, 4),
                                                 source=source)))
        key = "exec.fs_ok" if ctx.fs >= 1.0 else "exec.fs_low"
        sentences.append(tr.t(key, fs=tr.number(ctx.fs, 3)))
    elif stress is not None:
        rows.append((tr.t("exec.safety"), tr.t("exec.safety_none")))
        sentences.append(tr.t("exec.no_yield"))
    if smax is not None and smax.singularity_near:
        sentences.append(tr.t("exec.singular", n=ctx.numbers[smax], label=smax.singularity_near))
    eq = inputs.equilibrium
    if eq is not None:
        rows.append((tr.t("quality.equilibrium"), tr.t("eq.status." + eq.status.value)))
        if eq.status is EquilibriumStatus.IMBALANCE:
            sentences.append(tr.t("exec.equilibrium", residual=tr.number(100 * eq.residual, 2)))
    zz = inputs.error_estimate
    if zz is not None and zz.available:
        rows.append((tr.t("quality.error"), tr.number(100 * zz.relative_error, 3) + " %"))
        sentences.append(tr.t("exec.error", eta=tr.number(100 * zz.relative_error, 3)))
    q = inputs.mesh_quality
    if q is not None and q.invalid_elements:
        sentences.append(tr.t("exec.invalid", n=q.invalid_elements))
    alerts = _alerts(ctx)
    rows.append((tr.t("exec.alerts"), str(alerts) if alerts else tr.t("exec.alerts_none")))
    blocks = [Table(header=(), rows=tuple(rows), widths=(0.36, 0.64))]
    if inputs.config.intro_text:
        blocks.insert(0, Paragraph(inputs.config.intro_text))  # user text, never translated
    if sentences:
        blocks.append(BulletList(tuple(sentences)))
    return blocks


def _section_assumptions(ctx: FemContext, tr: Translator, level) -> list:
    """What the analysis assumes and what the report does not assess (step d)."""
    inputs = ctx.inputs
    res = inputs.result
    system = inputs.config.unit_system.value
    units = Paragraph(tr.t("note.units", system=tr.t("note.units." + system)))
    if level is ReportLevel.QUICK:
        return [Paragraph(tr.t("assume.short")), units]
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
    singular = sum(1 for h in inputs.hotspots if h.singularity_near)
    if singular:
        dependence.append(tr.t("assume.singular", n=singular))
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
        "trace.report_value", level=tr.t("report.level." + config.level.value),
        language=config.language, units=tr.t("note.units." + config.unit_system.value))))
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
    if q is not None and level is ReportLevel.FULL:
        labels = tuple("%s–%s" % (tr.number(i / 10, 1), tr.number((i + 1) / 10, 1))
                       for i in range(10))
        blocks.append(BarChart(title=tr.t("quality.histogram"), labels=labels,
                               values=tuple(float(v) for v in q.histogram),
                               caption=tr.t("quality.histogram_caption"),
                               x_title=tr.t("quality.histogram_x"),
                               y_title=tr.t("quality.histogram_y")))
    return blocks


def _error_figure(ctx: FemContext, tr: Translator) -> Figure:
    inputs = ctx.inputs
    index = len(inputs.views)  # the error map is captured after the regular views
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
        level_label=tr.t("report.level." + config.level.value),
        level_caption=tr.t("report.level"),
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
