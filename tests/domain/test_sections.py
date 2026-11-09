# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import pytest

from freecad.PartReview.domain.blocks import Heading, Paragraph, Table
from freecad.PartReview.domain.i18n import Translator
from freecad.PartReview.domain.models import ReportLevel
from freecad.PartReview.domain.report import build_report
from freecad.PartReview.domain.sections import (
    ALL_LEVELS,
    DETAILED_LEVELS,
    Section,
    SectionRegistry,
    compose,
)

from test_i18n_report import make_inputs

TR = Translator("en", strict=True)


def para(text):
    return lambda ctx, tr, level: [Paragraph(text)]


def test_registry_rejects_duplicates_and_sorts_by_order():
    reg = SectionRegistry([Section("b", 200, "section.summary", ALL_LEVELS, para("B")),
                           Section("a", 100, "section.views", ALL_LEVELS, para("A"))])
    assert [s.key for s in reg] == ["a", "b"]
    with pytest.raises(ValueError):
        reg.register(Section("a", 300, "section.assumptions", ALL_LEVELS, para("x")))


def test_compose_filters_by_level_applies_and_empty_content():
    reg = SectionRegistry([
        Section("one", 10, "section.views", ALL_LEVELS, para("1")),
        Section("detail", 20, "section.points", DETAILED_LEVELS, para("2")),
        Section("off", 30, "section.summary", ALL_LEVELS, para("3"), applies=lambda c: False),
        Section("empty", 40, "section.results", ALL_LEVELS, lambda c, t, l: []),
        Section("last", 50, "section.assumptions", ALL_LEVELS, para("5")),
    ])
    blocks, toc = compose(None, TR, reg, ReportLevel.QUICK)
    assert [h.text for h in blocks if isinstance(h, Heading)] == ["1. Views", "2. Assumptions and limitations"]
    assert [(e.number, e.anchor) for e in toc] == [(1, "one"), (2, "last")]
    blocks, toc = compose(None, TR, reg, ReportLevel.FULL)
    assert [e.anchor for e in toc] == ["one", "detail", "last"]
    assert blocks[0] == Heading("1. Views", anchor="one")


def test_a_new_section_plugs_in_without_touching_the_engine():
    """What phase 4/5 will do: register an extra section (e.g. DFM) in its place."""
    from freecad.PartReview.domain.report import FEM_SECTIONS
    reg = SectionRegistry(list(FEM_SECTIONS) + [
        Section("dfm.findings", 500, "section.summary", ALL_LEVELS, para("DFM here"))])
    doc = build_report(make_inputs(), TR, registry=reg)
    texts = [b.text for b in doc.blocks if isinstance(b, Paragraph)]
    assert "DFM here" in texts
    assert [e.anchor for e in doc.toc][-3:] == ["dfm.findings", "fem.glossary",
                                                "fem.assumptions"]


@pytest.mark.parametrize("level, has_points, has_toc, full_cover", [
    (ReportLevel.QUICK, False, False, False),
    (ReportLevel.STANDARD, True, True, True),
    (ReportLevel.FULL, True, True, True),
])
def test_fem_report_levels(level, has_points, has_toc, full_cover):
    inputs = make_inputs()
    inputs.config.level = level
    doc = build_report(inputs, TR)
    anchors = [b.anchor for b in doc.blocks if isinstance(b, Heading)]
    assert ("fem.points" in anchors) == has_points
    assert bool(doc.toc) == has_toc
    assert doc.cover.full_page == full_cover
    assert anchors[0] == "fem.executive" and anchors[1] == "fem.views"
    assert anchors[-1] == "fem.assumptions"  # no traceability data in this test
    assert any(isinstance(b, Table) for b in doc.blocks)


def test_cover_keeps_user_texts_without_the_level():
    inputs = make_inputs()
    inputs.config.company = "Oficina São José Ltda."
    doc = build_report(inputs, Translator("pt_BR", strict=True))
    assert doc.cover.title == "Suporte do motor"
    assert doc.cover.subtitle == "Relatório de análise estrutural (FEM)"
    assert doc.cover.company == "Oficina São José Ltda."
    assert not any("Completo" in v for _, v in doc.cover.info)  # no report level (owner)
    assert doc.header_text == "Suporte do motor"


def test_toc_lists_sections_in_order_with_titles():
    doc = build_report(make_inputs(), Translator("pt_BR", strict=True))
    assert doc.toc_title == "Sumário"
    assert [(e.number, e.title) for e in doc.toc][:2] == [(1, "Resumo executivo"), (2, "Vistas")]
    headings = [b.text for b in doc.blocks if isinstance(b, Heading)]
    assert headings == ["%d. %s" % (e.number, e.title) for e in doc.toc]
