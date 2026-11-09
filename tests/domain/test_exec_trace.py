# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import datetime

from freecad.PartReview.domain.blocks import BulletList, Heading, Notice, Paragraph, Table
from freecad.PartReview.domain.i18n import Translator
from freecad.PartReview.domain.models import ReportLevel
from freecad.PartReview.domain.report import build_report
from freecad.PartReview.domain.trace import Traceability
from freecad.PartReview.domain.units import Quantity

from test_i18n_report import make_inputs


def trace(unsaved=False):
    return Traceability(
        tool_version="1.0.0", freecad_version="1.1.4 (build 45039, commit 4fd3bf32)",
        generated_at=datetime.datetime(2026, 11, 7, 10, 30), platform="Linux",
        python_version="3.13.16", file_name="a.FCStd", file_path="/x/a.FCStd",
        file_sha256="ab" * 32, file_modified=datetime.datetime(2026, 11, 6, 22, 9),
        unsaved_changes=unsaved, result_name="CCX_Results", result_label="CCX_Results",
        solver="CalculiX", analysis_type="static",
        solver_settings=(("AnalysisType", "static"), ("GeometricalNonlinearity", "linear"),
                         ("MaterialNonlinearity", "linear")),
        mesher="Gmsh (FEMMeshGmsh)", mesher_settings=(("ElementOrder", "2nd"),))


def section(doc, anchor):
    blocks = list(doc.blocks)
    i = next(k for k, b in enumerate(blocks) if isinstance(b, Heading) and b.anchor == anchor)
    j = next((k for k, b in enumerate(blocks[i + 1:], i + 1) if isinstance(b, Heading)),
             len(blocks))
    return blocks[i + 1:j]


def text_of(blocks):
    out = []
    for b in blocks:
        if isinstance(b, Table):
            out += [c for row in b.rows for c in row]
        elif isinstance(b, BulletList):
            out += list(b.items)
        elif isinstance(b, (Paragraph, Notice)):
            out.append(b.text)
    return "\n".join(out)


def test_executive_summary_states_verdict_from_data():
    inputs = make_inputs(Quantity(5.0, "MPa"))  # max 10 MPa -> FS 0.5
    doc = build_report(inputs, Translator("pt_BR", strict=True))
    text = text_of(section(doc, "fem.executive"))
    assert "10,0 MPa — ponto 1" in text
    assert "ULTRAPASSA O LIMITE" in text and "0,500" in text and "o material escoaria" in text
    # the max sits on a load face and no regular point is known: the peak is used
    # (safe side), labelled as such, and the singularity is still explained
    assert "no máximo da peça" in text and "singularidade" in text


def test_executive_summary_without_yield_does_not_conclude():
    doc = build_report(make_inputs(), Translator("en", strict=True))
    text = text_of(section(doc, "fem.executive"))
    assert "not computed: yield strength not given" in text
    assert "No conclusion on strength" in text


def test_assumptions_follow_solver_settings_and_list_what_is_not_assessed():
    inputs = make_inputs()
    inputs.trace = trace()
    text = text_of(section(build_report(inputs, Translator("pt_BR", strict=True)),
                           "fem.assumptions"))
    assert "Pequenos deslocamentos" in text and "Aço: elástico linear" in text
    assert "fadiga" in text and "flambagem" in text
    assert "Apoios fixos" in text
    # each assumption says briefly what would be better
    assert "Carga que se repete ou bate" in text


def test_quick_assumptions_are_one_paragraph():
    inputs = make_inputs()
    inputs.config.level = ReportLevel.QUICK
    blocks = section(build_report(inputs, Translator("en", strict=True)), "fem.assumptions")
    assert all(isinstance(b, Paragraph) for b in blocks) and len(blocks) == 2


def test_traceability_section_and_footer_hash():
    inputs = make_inputs()
    inputs.trace = trace(unsaved=True)
    doc = build_report(inputs, Translator("pt_BR", strict=True))
    text = text_of(section(doc, "fem.trace"))
    assert "ab" * 32 in text and "1.1.4 (build 45039, commit 4fd3bf32)" in text
    assert "GeometricalNonlinearity = linear" in text and "Gmsh (FEMMeshGmsh)" in text
    assert "alterações não salvas" in text
    assert "SHA-256" not in doc.footer  # hash only in the Traceability section
    inputs.config.level = ReportLevel.QUICK
    quick = build_report(inputs, Translator("pt_BR", strict=True))
    assert "fem.trace" not in [b.anchor for b in quick.blocks if isinstance(b, Heading)]


def test_single_figure_reference_is_singular():
    from freecad.PartReview.domain.models import ReportLevel
    inputs = make_inputs()
    inputs.config.level = ReportLevel.QUICK
    inputs.views = [v for v in inputs.views if v.is_overview]
    text = text_of(section(build_report(inputs, Translator("pt_BR", strict=True)), "fem.executive"))
    # figure 1 = supports and loads; the stress overview is figure 2
    assert "(figura 2)" in text and "(figuras 2)" not in text
