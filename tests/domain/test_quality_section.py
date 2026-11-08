# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import pytest

from freecad.PartReview.domain.blocks import BarChart, Figure, Heading, Notice, Table
from freecad.PartReview.domain.i18n import Translator
from freecad.PartReview.domain.models import FieldKind, ReportLevel, ResultField, Vec3
from freecad.PartReview.domain.quality import (
    EquilibriumCheck,
    EquilibriumStatus,
    ErrorEstimate,
    check_equilibrium,
    mesh_quality,
)
from freecad.PartReview.domain.report import build_report

from test_i18n_report import make_inputs
from test_surface_hotspots import bar_mesh


def with_quality(level, equilibrium=None, error=True):
    inputs = make_inputs()
    inputs.config.level = level
    mesh, elements = bar_mesh(6)
    inputs.mesh_quality = mesh_quality(elements, mesh.node_positions)
    inputs.equilibrium = equilibrium or check_equilibrium(Vec3(0, 0, -18.0), Vec3(0, 0, 16.43))
    if error:
        ids = tuple(inputs.result.mesh.node_positions)
        inputs.error_estimate = ErrorEstimate(True, 0.16, 0.88, 0.22, 0)
        inputs.error_field = ResultField(FieldKind.ESTIMATED_ERROR, "%", ids,
                                         tuple(float(i % 7) for i in range(len(ids))))
        inputs.error_view = inputs.views[0]
    return inputs


def quality_blocks(doc):
    blocks = list(doc.blocks)
    start = next(i for i, b in enumerate(blocks)
                 if isinstance(b, Heading) and b.anchor == "fem.quality")
    end = next((i for i, b in enumerate(blocks[start + 1:], start + 1)
                if isinstance(b, Heading)), len(blocks))
    return blocks[start + 1:end]


def test_full_level_has_table_alert_map_and_histogram():
    inputs = with_quality(ReportLevel.FULL)
    doc = build_report(inputs, Translator("pt_BR", strict=True))
    blocks = quality_blocks(doc)
    table = blocks[0]
    text = "\n".join(v for _, v in table.rows)
    assert "16,0 %" in text and "Não fecha" in text and "= 8,7 %" in text
    assert any(isinstance(b, Notice) and "não equilibram" in b.text for b in blocks)
    figure = next(b for b in blocks if isinstance(b, Figure))
    # captured right after the supports/loads views and the regular views
    assert figure.view_index == len(inputs.boundary_views) + len(inputs.views)
    assert figure.legend.title.startswith("Erro local estimado")
    assert any(isinstance(b, BarChart) and sum(b.values) == 36 for b in blocks)  # 6 cubes x 6


def test_quick_level_keeps_only_the_verdict_rows():
    doc = build_report(with_quality(ReportLevel.QUICK), Translator("en", strict=True))
    blocks = quality_blocks(doc)
    assert not any(isinstance(b, (Figure, BarChart)) for b in blocks)
    labels = [k for k, _ in blocks[0].rows]
    assert labels == ["Inverted or degenerate elements",
                      "Equilibrium (applied loads + reactions = 0)",
                      "Estimated analysis error (ZZ indicator, energy norm)"]


def test_unavailable_items_say_why():
    eq = EquilibriumCheck(EquilibriumStatus.NOT_AVAILABLE, reason_key="eq.reason.no_dat")
    inputs = with_quality(ReportLevel.STANDARD, equilibrium=eq, error=False)
    inputs.error_estimate = ErrorEstimate(False, reason_key="zz.reason.material")
    doc = build_report(inputs, Translator("pt_BR", strict=True))
    text = "\n".join(v for b in quality_blocks(doc) if isinstance(b, Table) for _, v in b.rows)
    assert "Não disponível: o documento não tem o texto de reações" in text
    assert "não disponível: a estimativa exige um único material" in text


def test_load_on_supports_is_explained_in_the_report():
    eq = check_equilibrium(Vec3(0, 0, -18.0), Vec3(0, 0, 17.196),
                           load_on_supports=Vec3(0, 0, -0.804))
    assert eq.status is EquilibriumStatus.VERIFIED
    inputs = with_quality(ReportLevel.STANDARD, equilibrium=eq, error=False)
    doc = build_report(inputs, Translator("pt_BR", strict=True))
    text = "\n".join(v for b in quality_blocks(doc) if isinstance(b, Table) for _, v in b.rows)
    assert "Verificado" in text and "nós que também estão no apoio fixo" in text
    assert "4,47 %" in text
    plain = check_equilibrium(Vec3(0, 0, -9e6), Vec3(0, 0, 9e6))
    doc = build_report(with_quality(ReportLevel.STANDARD, equilibrium=plain, error=False),
                       Translator("en", strict=True))
    text = "\n".join(v for b in quality_blocks(doc) if isinstance(b, Table) for _, v in b.rows)
    assert "also fixed" not in text


def test_convergence_study_from_the_optimiser():
    from freecad.PartReview.domain.quality import ConvergencePass
    inputs = with_quality(ReportLevel.FULL)
    inputs.convergence = [ConvergencePass(5000, 0.09, 0.19, 0.40, 1.00e-4),
                          ConvergencePass(8000, 0.076, 0.17, 0.41, 1.02e-4)]
    blocks = quality_blocks(build_report(inputs, Translator("pt_BR", strict=True)))
    table = next(b for b in blocks if isinstance(b, Table) and b.header
                 and b.header[0] == "Rodada")
    assert [r[1] for r in table.rows] == ["5 000", "8 000"]
    note = next(b for b in blocks if isinstance(b, Notice) and "duas últimas" in b.text)
    assert "2,4 %" in note.text and "estáveis" in note.text  # 0.01/0.41, 0.02/1.02
