# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""From a ReportConfig to a PDF: read, find hotspots, plan views, capture, write.

Runs in the GUI thread (the FreeCAD API is not thread-safe). Long steps call
``progress(message, fraction)``, which may raise ``Cancelled`` (rule 8).
"""

import datetime
import os
from dataclasses import replace
import shutil
import tempfile

import FreeCAD as App  # type: ignore
import FreeCADGui as Gui  # type: ignore

from .. import __version__
from ..domain import camera_planner as cp
from ..domain import colormap
from ..domain import geometry as g
from ..domain.hotspots import (
    constraint_hotspot,
    drop_redundant,
    field_hotspots,
    gradient_hotspot,
    mark_singularities,
)
from ..domain.i18n import Translator
from ..domain.models import ConstraintKind, FieldKind, ReportLevel, ResultField, Vec3
from ..domain.quality import (
    EquilibriumCheck,
    EquilibriumStatus,
    ErrorEstimate,
    check_equilibrium,
    load_on_fixed_nodes,
    mesh_quality,
    parse_ccx_totals,
)
from ..domain.exporters import nodal_csv
from ..domain.report import ReportInputs, build_report, order_hotspots, views_for_level
from ..domain.surface import build_surface
from . import fem_reader, trace_reader
from .error_estimator import estimate
from .html_writer import write_html
from .logo_loader import inspect_logo
from .pdf_writer import write_pdf
from .view_state import ViewState
from .visibility import RayVisibility

IMAGE_SIZE = (1600, 1200)


class Cancelled(Exception):
    """The user cancelled the report."""


class ConfigError(Exception):
    """Invalid ReportConfig; ``key`` is an i18n message key."""

    def __init__(self, key):
        super().__init__(key)
        self.key = key


def _no_progress(message, fraction):
    return None


def _yield_strength(config, result, stress_unit):
    """(Quantity in the stress unit, source) or (None, '')."""
    if config.yield_strength.strip():
        return fem_reader.parse_quantity_as(config.yield_strength, stress_unit), "user"
    for material in result.materials:
        if material.yield_strength is not None:
            return fem_reader.convert(material.yield_strength, stress_unit), "material"
    return None, ""


def _plan(result, surface, max_views):
    """Hotspots (numbered order) and selected views."""
    mesh = result.mesh
    low, high = mesh.bounding_box()
    center = g.scale(g.add(low, high), 0.5)
    radius = 0.5 * g.distance(low, high)
    stress = result.get_field(FieldKind.VON_MISES)
    disp = result.get_field(FieldKind.DISPLACEMENT)

    if surface is None:
        def is_visible(point, direction):
            return True
        spots = []
    else:
        is_visible = RayVisibility(mesh.node_positions, surface.triangles,
                                   epsilon=0.05 * surface.mean_edge_length)
        spots = []
        if stress is not None:
            spots += field_hotspots(stress, mesh, surface)
            grad = gradient_hotspot(stress, mesh, surface)
            if grad is not None:
                spots.append(grad)
        if disp is not None:
            spots += field_hotspots(disp, mesh, surface)
        spots += [h for h in (constraint_hotspot(c) for c in result.constraints) if h]
        tolerance = max(1.5 * surface.mean_edge_length, 0.01 * radius)
        spots = order_hotspots(drop_redundant(
            mark_singularities(spots, result.constraints, tolerance)))

    views = []
    for kind in (FieldKind.VON_MISES, FieldKind.DISPLACEMENT):
        if result.get_field(kind) is not None:
            views.append(cp.plan_overview(kind, spots, center, radius, is_visible))
    views += [cp.plan_target_view(s, center, radius, is_visible) for s in spots]
    return spots, cp.select_views(views, max_views=max_views)


def _equilibrium(analysis, result):
    """Sum of applied forces vs CalculiX reactions (decision 004)."""
    if any(c.kind not in (ConstraintKind.FIXED, ConstraintKind.FORCE) for c in result.constraints):
        return EquilibriumCheck(EquilibriumStatus.NOT_VERIFIABLE, reason_key="eq.reason.load_types")
    text = fem_reader.ccx_dat_text(analysis)
    totals = parse_ccx_totals(text) if text else {}
    if not totals:
        return EquilibriumCheck(EquilibriumStatus.NOT_AVAILABLE, reason_key="eq.reason.no_dat")
    applied = Vec3(0.0, 0.0, 0.0)
    for c in result.constraints:
        if c.kind is ConstraintKind.FORCE and c.magnitude is not None and c.direction is not None:
            newtons = fem_reader.convert(c.magnitude, "N").value
            applied = g.add(applied, g.scale(g.normalize(c.direction), newtons))
    reactions = Vec3(0.0, 0.0, 0.0)
    for vector in totals.values():
        reactions = g.add(reactions, vector)
    check = check_equilibrium(applied, reactions)
    if check.status is EquilibriumStatus.IMBALANCE:
        # Loads on nodes that are also fixed are missing from CalculiX reaction totals
        # (spike 8.0, decision 007). Computed only when needed: it is not free.
        data = fem_reader.nodal_loads_and_fixed_nodes(analysis)
        if data is not None:
            check = check_equilibrium(applied, reactions,
                                      load_on_supports=load_on_fixed_nodes(*data))
    return check


def _error_estimate(analysis, result_obj, result, tets):
    """(ErrorEstimate, nodal indicator field in %) - decision 005."""
    if not tets:
        return ErrorEstimate(False, reason_key="zz.reason.elements"), None
    constants = fem_reader.elastic_constants(analysis)
    if constants is None:
        return ErrorEstimate(False, reason_key="zz.reason.material"), None
    positions = {n: tuple(p) for n, p in result.mesh.node_positions.items()}
    zz = estimate(positions, result.elements, fem_reader.read_displacement_vectors(result_obj),
                  *constants)
    local = sorted(zz.element_relative.tolist())
    p95 = local[int(0.95 * (len(local) - 1))]
    field = ResultField(FieldKind.ESTIMATED_ERROR, "%", tuple(zz.node_ids.tolist()),
                        tuple((100.0 * zz.node_indicator).tolist()))
    return ErrorEstimate(True, zz.relative_error, local[-1], p95, zz.invalid_elements), field


def generate_fem_report(doc, config, progress=_no_progress):
    """Create the PDF (and the CSV/HTML exports asked for); returns the written paths."""
    errors = config.validate()
    if config.logo_path:
        logo_error = inspect_logo(config.logo_path)[0]
        if logo_error:
            errors.append(logo_error)
    if errors:
        raise ConfigError(errors[0])
    tr = Translator(config.language)

    progress(tr.t("progress.reading"), 0.05)
    unsaved = Gui.getDocument(doc.Name).Modified  # read before ViewState touches the view
    result = fem_reader.read_fem_result(doc, config.result_name, config.unit_system)
    result_obj = doc.getObject(config.result_name)
    mesh_obj = result_obj.Mesh
    analysis = fem_reader.find_analysis(result_obj)
    stress = result.get_field(FieldKind.VON_MISES)
    yield_q, yield_source = (_yield_strength(config, result, stress.unit)
                             if stress is not None else (None, ""))

    progress(tr.t("progress.surface"), 0.15)
    tets = bool(result.elements) and all(len(e) in (4, 10) for e in result.elements)
    surface = build_surface(result.elements, result.mesh.node_positions) if tets else None

    progress(tr.t("progress.quality"), 0.2)
    equilibrium = _equilibrium(analysis, result)
    max_node = stress.maximum(result.mesh).node_id if stress is not None else None
    quality = mesh_quality(result.elements, result.mesh.node_positions, max_node) if tets else None
    zz, error_field = _error_estimate(analysis, result_obj, result, tets)

    progress(tr.t("progress.hotspots"), 0.3)
    spots, views = _plan(result, surface, views_for_level(config))
    progress(tr.t("progress.planning"), 0.4)
    error_view = None
    if error_field is not None and views and config.level is not ReportLevel.QUICK:
        error_view = replace(views[0], color_field=FieldKind.ESTIMATED_ERROR, targets=())
    fields = dict(result.fields)
    if error_field is not None:
        fields[FieldKind.ESTIMATED_ERROR] = error_field

    workdir = tempfile.mkdtemp(prefix="partreview_")
    try:
        image_paths = []
        shots = views + ([error_view] if error_view is not None else [])
        with ViewState(doc) as vs:
            vs.show_only([mesh_obj])
            vs.set_backface_culling(mesh_obj, False)
            colored = None
            for i, view in enumerate(shots):
                progress(tr.t("progress.capture", n=i + 1, total=len(shots)),
                         0.4 + 0.5 * i / max(1, len(shots)))
                if view.color_field is not colored:
                    f = fields[view.color_field]
                    vs.color_nodes(mesh_obj, f.node_ids,
                                   colormap.scalars_for_freecad(f.values, min(f.values),
                                                                max(f.values)))
                    colored = view.color_field
                vs.apply_camera(view.camera)
                path = os.path.join(workdir, "view_%02d.png" % i)
                vs.save_image(path, *IMAGE_SIZE)
                image_paths.append(path)

        progress(tr.t("progress.pdf"), 0.95)
        max_on_surface = None
        if surface is not None and stress is not None:
            max_on_surface = max_node in surface.nodes
        inputs = ReportInputs(
            result=result, config=config, hotspots=spots, views=views, image_size=IMAGE_SIZE,
            document_name=os.path.basename(doc.FileName) or doc.Label,
            date=datetime.date.today(), yield_strength=yield_q, yield_source=yield_source,
            max_on_surface=max_on_surface, surface_available=surface is not None,
            tool_version=__version__, freecad_version=".".join(App.Version()[:3]),
            equilibrium=equilibrium, mesh_quality=quality, error_estimate=zz,
            error_field=error_field, error_view=error_view,
            trace=trace_reader.collect(doc, result_obj, analysis, result.solver,
                                       result.analysis_type, __version__, unsaved))
        document = build_report(inputs, tr)
        write_pdf(document, image_paths, config.output_path)
        written = [config.output_path]
        if config.export_html:
            written.append(write_html(document, image_paths, config.extra_output(".html"),
                                      config.language))
        if config.export_csv:
            path = config.extra_output(".csv")
            extra = [error_field] if error_field is not None else []
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(nodal_csv(result, tr, extra))
            written.append(path)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    progress("", 1.0)
    return written
