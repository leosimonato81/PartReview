# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""The report's conclusion: one design safety factor, verdict only against the
user's required factor."""

import pytest

from freecad.PartReview.domain.blocks import Notice
from freecad.PartReview.domain.design_check import design_check, parse_required
from freecad.PartReview.domain.i18n import Translator
from freecad.PartReview.domain.models import ReportConfig
from freecad.PartReview.domain.report import build_report
from freecad.PartReview.domain.units import Quantity

from test_i18n_report import make_inputs


def mpa(v):
    return Quantity(v, "MPa")


def test_design_stress_away_from_supports_decides():
    check = design_check(mpa(250), "user", mpa(50), mpa(200))
    c = check.governing
    assert c.design_is_regular and check.fs == pytest.approx(5.0)
    assert c.fs_peak == pytest.approx(1.25)  # the singular peak is only reported
    assert check.status == "number"  # no requirement typed: only the number


def test_unknown_design_stress_uses_the_peak():
    check = design_check(mpa(250), "user", None, mpa(200))
    assert not check.governing.design_is_regular and check.fs == pytest.approx(1.25)


@pytest.mark.parametrize("required, status", [(2.0, "meets"), (5.0, "meets"),
                                              (6.0, "fails"), (None, "number")])
def test_verdict_only_against_the_required_factor(required, status):
    assert design_check(mpa(250), "user", mpa(50), mpa(200), required=required).status == status


def test_below_one_exceeds_the_limit_even_without_requirement():
    assert design_check(mpa(40), "user", mpa(50), mpa(200)).status == "exceeds"


def test_polymer_smallest_factor_governs():
    # PLA: limit 26,4 (UTS); von Mises design 5 -> 5,28; Rankine design 8 -> 3,30
    check = design_check(mpa(26.4), "material_uts", mpa(5), mpa(10), family="polymer",
                         ultimate=mpa(26.4), s1_design=mpa(8), s1_peak=mpa(9))
    assert check.governing.key == "rankine" and check.fs == pytest.approx(3.3)
    # metals: Rankine is not used
    metal = design_check(mpa(250), "user", mpa(5), mpa(10), family="metal",
                         ultimate=mpa(400), s1_design=mpa(300), s1_peak=mpa(300))
    assert [c.key for c in metal.criteria] == ["von_mises"]


def test_no_limit_or_compression_only_gives_no_criterion():
    assert design_check(None, "", mpa(5), mpa(10)) is None
    check = design_check(mpa(26.4), "material", mpa(5), mpa(10), family="polymer",
                         ultimate=mpa(26.4), s1_design=mpa(-3), s1_peak=mpa(-1))
    assert [c.key for c in check.criteria] == ["von_mises"]  # no tension: no Rankine


@pytest.mark.parametrize("text, value", [("", None), ("2", 2.0), ("1,5", 1.5), (" 1.25 ", 1.25)])
def test_parse_required(text, value):
    assert parse_required(text) == value


@pytest.mark.parametrize("text", ["abc", "0.8", "-2", "nan"])
def test_parse_required_refuses(text):
    with pytest.raises(ValueError):
        parse_required(text)
    config = ReportConfig(result_name="R", output_path="a.pdf", required_safety=text)
    assert "config.error.required_safety" in config.validate()


def test_conclusion_is_the_first_block_of_the_summary():
    inputs = make_inputs(Quantity(25.0, "MPa"))  # max 10 MPa -> FS 2,5 (peak used)
    inputs.config.required_safety = "2"
    doc = build_report(inputs, Translator("pt_BR", strict=True))
    start = next(i for i, b in enumerate(doc.blocks)
                 if getattr(b, "anchor", "") == "fem.executive")
    first = doc.blocks[start + 1]
    assert isinstance(first, Notice) and first.level == "ok"
    assert first.text.startswith("ATENDE") and "2,50" in first.text and "(2,00)" in first.text
    inputs.config.required_safety = "3"
    doc = build_report(inputs, Translator("en", strict=True))
    notice = next(b for b in doc.blocks if isinstance(b, Notice))
    assert notice.text.startswith("DOES NOT MEET") and notice.level == "warning"


def test_glossary_lists_only_the_concepts_of_this_report():
    def glossary(doc):
        start = next(i for i, b in enumerate(doc.blocks)
                     if getattr(b, "anchor", "") == "fem.glossary")
        return [row[0] for row in doc.blocks[start + 1].rows]

    tr = Translator("pt_BR", strict=True)
    plain = glossary(build_report(make_inputs(), tr))  # no material limit
    assert "FS de projeto" not in plain and "Von Mises" in plain and "Rankine" not in plain
    inputs = make_inputs(Quantity(25.0, "MPa"))
    inputs.config.required_safety = "2"
    terms = glossary(build_report(inputs, tr))
    assert terms[:3] == ["FS de projeto", "Tensão de projeto", "FS exigido"]


def _texts(doc):
    out = []
    for b in doc.blocks:
        if hasattr(b, "rows"):
            out += [c for row in b.rows for c in row]
        elif hasattr(b, "text"):
            out.append(b.text)
    return "\n".join(out)


def test_margin_over_the_required_factor_is_a_load_multiplier():
    inputs = make_inputs(Quantity(50.0, "MPa"))  # max 10 MPa -> FS 5 (peak used)
    inputs.config.required_safety = "2"
    t = _texts(build_report(inputs, Translator("pt_BR", strict=True)))
    assert "a carga pode crescer até 2,5× a atual" in t  # 5 / 2
    inputs.config.required_safety = "8"
    t = _texts(build_report(inputs, Translator("pt_BR", strict=True)))
    assert "reduza a tensão de projeto em 38 %" in t  # 1 - 5/8


def test_assumptions_say_how_to_choose_the_limit_and_the_factor():
    tr = Translator("pt_BR", strict=True)
    t = _texts(build_report(make_inputs(), tr))  # nothing given
    assert "Sem limite do material" in t
    inputs = make_inputs(Quantity(250.0, "MPa"))
    t = _texts(build_report(inputs, tr))  # given, no required SF
    assert "Sem FS exigido" in t and "Shigley" in t
    inputs.config.required_safety = "2"
    t = _texts(build_report(inputs, tr))
    assert "FS exigido: 2,00" in t and "fadiga" in t


def test_results_from_another_mesh_are_flagged_first():
    inputs = make_inputs(Quantity(250.0, "MPa"))
    inputs.stale_mesh = (63000, 57000)
    doc = build_report(inputs, Translator("pt_BR", strict=True))
    start = next(i for i, b in enumerate(doc.blocks)
                 if getattr(b, "anchor", "") == "fem.executive")
    first = doc.blocks[start + 1]
    assert isinstance(first, Notice) and "outra malha (57 000 nós)" in first.text
