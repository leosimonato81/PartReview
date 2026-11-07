# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import json

import pytest

from freecad.PartReview.domain.i18n import Translator
from freecad.PartReview.domain.models import ReportConfig, ReportLevel, UnitSystem
from freecad.PartReview.domain.report import build_report
from freecad.PartReview.domain.templates import ReportTemplate, accent_rgb, file_stem

from test_i18n_report import make_inputs

TEMPLATE = ReportTemplate(name="Oficina São José", company="Oficina São José Ltda.",
                          responsible="Eng. Maria Silva", logo_path="/x/logo.png",
                          accent_color="#7a1f2b", intro_text="Relatório para o cliente X.",
                          disclaimer_text="Uso interno.", level="standard", language="en",
                          unit_system="freecad_schema")


def test_round_trip_through_json_keeps_user_texts():
    data = json.loads(json.dumps(TEMPLATE.to_dict()))
    assert data["format"] == 1
    assert ReportTemplate.from_dict(data) == TEMPLATE


@pytest.mark.parametrize("bad", [
    {"name": ""}, {"name": "x", "accent_color": "red"}, {"name": "x", "level": "huge"},
    {"name": "x", "language": "fr"}, {"name": "x", "unit_system": "imperial"},
    {"name": "x", "format": 99}, {"name": 3}, ["not", "a", "dict"],
])
def test_invalid_templates_are_rejected(bad):
    with pytest.raises(ValueError):
        ReportTemplate.from_dict(bad)


def test_unknown_keys_are_ignored_for_forward_compatibility():
    assert ReportTemplate.from_dict({"name": "x", "future_field": "y"}).name == "x"


def test_apply_and_capture_config():
    config = ReportConfig()
    TEMPLATE.apply_to(config)
    assert config.company == "Oficina São José Ltda." and config.author == "Eng. Maria Silva"
    assert config.level is ReportLevel.STANDARD and config.unit_system is UnitSystem.FREECAD_SCHEMA
    assert ReportTemplate.from_config("Oficina São José", config) == TEMPLATE


def test_template_colour_and_texts_reach_the_document():
    inputs = make_inputs()
    TEMPLATE.apply_to(inputs.config)
    inputs.config.language = "pt_BR"
    doc = build_report(inputs, Translator("pt_BR", strict=True))
    assert doc.accent == pytest.approx(accent_rgb("#7a1f2b"))
    texts = [getattr(b, "text", "") for b in doc.blocks]
    assert "Relatório para o cliente X." in texts and "Uso interno." in texts


def test_file_stem_is_safe():
    assert file_stem("Oficina São José / v2") == "Oficina_São_José_v2"
    assert file_stem("../../etc") == "etc"
    assert file_stem("   ") == "template"
