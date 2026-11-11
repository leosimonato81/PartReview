# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Texts of the mesh assistant panel: plain words first, numbers right after (pure)."""

from .geometry_summary import GeometryIssue, GeometrySummary
from .mesh_budget import BudgetCheck, MachineProfile, FITS_FRACTION
from .mesh_sizing import MeshOption


def mm(tr, value) -> str:
    return tr.number(value, 3) + " mm"


def memory(tr, mb) -> str:
    return (tr.number(mb / 1024.0, 3) + " GB") if mb >= 1024.0 else (tr.integer(mb) + " MB")


def part_rows(summary: GeometrySummary, tr) -> list:
    """(label, value, tooltip) rows describing the part."""
    x, y, z = summary.size
    t = summary.characteristic_thickness
    return [
        (tr.t("ma.part.size"), "%s × %s × %s mm" % (tr.number(x, 3), tr.number(y, 3),
                                                   tr.number(z, 3)), ""),
        (tr.t("ma.part.volume"), tr.number(summary.volume, 3) + " mm³", ""),
        (tr.t("ma.part.thickness"), mm(tr, t), tr.t("ma.part.thickness_tip")),
        (tr.t("ma.part.topology"), tr.t("ma.part.topology_value", faces=summary.faces,
                                        edges=summary.edges), ""),
    ]


def issue_text(issue: GeometryIssue, summary: GeometrySummary, tr) -> str:
    t = summary.characteristic_thickness
    ratio = tr.number(t / issue.size, 2) if issue.size > 0 else "∞"
    return tr.t("ma.issue." + issue.kind.value, size=mm(tr, issue.size), t=mm(tr, t),
                ratio=ratio, count=issue.count, where=", ".join(issue.elements[:4])
                + (" …" if len(issue.elements) > 4 else ""))


def machine_rows(machine: MachineProfile, model, probes, history, history_date, tr) -> list:
    """Step 2, one row per SOURCE of information, so the user sees what was read from
    the system, what was measured on this computer and what is only estimated.

    ``probes``: CalculiX trials on this part; ``history``: trials on earlier parts."""
    from .solver_model import format_duration
    system = tr.t("ma.src.system_value", total=memory(tr, machine.total_mb),
                  free=memory(tr, machine.available_mb), cores=machine.cores)
    if probes:
        nodes = sorted(p.nodes for p in probes)
        measured = tr.t("ma.src.measured_part", count=len(probes),
                        low=tr.integer(round(nodes[0], -3) / 1000),
                        high=tr.integer(round(nodes[-1], -3) / 1000),
                        memory=memory(tr, max(p.peak_mb for p in probes)),
                        seconds=format_duration(max(p.seconds for p in probes)),
                        error=int(round(100 * model.error)))
    elif history:
        measured = tr.t("ma.src.measured_history", count=len(history), date=history_date)
    else:
        measured = tr.t("ma.src.measured_none")
    budget = FITS_FRACTION * machine.available_mb
    if model.measured:
        estimated = tr.t("ma.src.estimated_part",
                         nodes=tr.integer(round(model.safe_max_nodes(memory_mb=budget), -3)))
    else:
        low = model.memory.inverse(budget)  # compact parts (safe side)
        high = (model.memory_low.inverse(budget) if model.memory_low is not None else low)
        estimated = tr.t("ma.src.estimated_band", low=tr.integer(round(low, -3)),
                         high=tr.integer(round(high, -3)))
    return [(tr.t("ma.src.system"), system), (tr.t("ma.src.measured"), measured),
            (tr.t("ma.src.estimated"), estimated)]


def option_reason(option: MeshOption, summary: GeometrySummary, tr) -> str:
    return tr.t(option.reason_key, size=mm(tr, option.max_size),
                t=mm(tr, summary.characteristic_thickness), d=mm(tr, summary.diagonal),
                per={"very_coarse": "2/3", "coarse": 1, "medium": 2, "fine": 3,
                     "very_fine": 4}.get(option.level.value, ""))


def nodes_estimate(option: MeshOption, tr) -> str:
    return tr.t("ma.nodes_estimate", low=tr.integer(round(option.nodes_low, -3)),
                high=tr.integer(round(option.nodes_high, -3)))


def status_text(check: BudgetCheck, tr) -> str:
    return tr.t("ma.status." + check.status.value)


def gmsh_settings(option: MeshOption, tr) -> str:
    """The exact Gmsh properties the assistant writes (for technical readers)."""
    return "\n".join([
        "CharacteristicLengthMax = %s" % mm(tr, option.max_size),
        "CharacteristicLengthMin = %s" % (mm(tr, option.min_size) if option.min_size
                                          else "0 (Gmsh)"),
        "MeshSizeFromCurvature = %d" % option.curvature,
        "ElementOrder = %s" % option.order,
        "SecondOrderLinear = %s" % option.straight_edges,
        "HighOrderOptimize = None",
        "MeshRegion.CharacteristicLength = %s" % (", ".join(
            "%s (%d)" % (mm(tr, size), len(faces)) for size, faces in option.radius_regions)
            or "—"),
    ])


def measured(tr, seconds, peak_mb):
    """'4 s · 85 MB'; a run shorter than the watchdog's sampling shows '< 1 s · —'
    instead of a misleading '0 s · 0 MB'."""
    from .solver_model import format_duration
    time_text = "< 1 s" if seconds < 1.0 else format_duration(seconds)
    memory_text = memory(tr, peak_mb) if peak_mb > 0 else "—"
    return "%s · %s" % (time_text, memory_text)
