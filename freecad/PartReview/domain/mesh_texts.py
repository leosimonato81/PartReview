# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Texts of the mesh assistant panel: plain words first, numbers right after (pure)."""

from .geometry_summary import GeometryIssue, GeometrySummary, IssueKind
from .mesh_budget import BudgetCheck, MachineProfile, max_nodes_for, FITS_FRACTION
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


def machine_text(machine: MachineProfile, tr) -> str:
    return tr.t("ma.machine", total=memory(tr, machine.total_mb),
                free=memory(tr, machine.available_mb), cores=machine.cores,
                max_nodes=tr.integer(round(max_nodes_for(FITS_FRACTION * machine.available_mb),
                                           -3)))


def option_reason(option: MeshOption, summary: GeometrySummary, tr) -> str:
    return tr.t(option.reason_key, size=mm(tr, option.max_size),
                t=mm(tr, summary.characteristic_thickness), d=mm(tr, summary.diagonal),
                per={"coarse": 1, "medium": 2, "fine": 3}[option.level.value])


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
    ])
