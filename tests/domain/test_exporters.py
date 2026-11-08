# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import csv
import io
import re

from freecad.PartReview.domain.exporters import nodal_csv, render_html
from freecad.PartReview.domain.i18n import Translator
from freecad.PartReview.domain.models import FieldKind, ResultField
from freecad.PartReview.domain.report import build_report

from test_i18n_report import make_inputs


def test_csv_has_units_and_one_row_per_node_pt_br():
    inputs = make_inputs()
    res = inputs.result
    ids = tuple(res.mesh.node_positions)
    err = ResultField(FieldKind.ESTIMATED_ERROR, "%", ids, tuple(1.5 for _ in ids))
    text = nodal_csv(res, Translator("pt_BR", strict=True), extra_fields=[err])
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    assert rows[0] == ["nó", "x [mm]", "y [mm]", "z [mm]", "Tensão de von Mises [MPa]",
                       "Deslocamento [mm]", "Erro local estimado (ZZ) [%]"]
    assert len(rows) == 1 + len(ids)
    assert rows[1][-1] == "1,5" and "." not in rows[1][1]


def test_csv_english_uses_comma_and_point():
    text = nodal_csv(make_inputs().result, Translator("en", strict=True))
    header, first = list(csv.reader(io.StringIO(text)))[:2]
    assert header[0] == "node" and len(header) == 6
    assert re.match(r"^-?\d+\.\d+", first[1])


def test_html_is_self_contained_and_escapes_user_text():
    inputs = make_inputs()
    inputs.config.company = "<Oficina & Cia>"
    doc = build_report(inputs, Translator("pt_BR", strict=True))
    uris = ["data:image/png;base64,AAA%d" % i for i in range(len(inputs.boundary_views) + len(inputs.views))]
    page = render_html(doc, uris, logo_uri="data:image/png;base64,LOGO")
    assert page.startswith("<!DOCTYPE html>") and 'lang="pt-BR"' in page
    assert "&lt;Oficina &amp; Cia&gt;" in page and "<Oficina" not in page
    for entry in doc.toc:
        assert 'href="#%s"' % entry.anchor in page and 'id="%s"' % entry.anchor in page
    assert page.count("<figure>") >= len(inputs.views)
    assert "http" not in page.replace("https://", "")  # no external resources



def test_html_logo_is_centered_at_the_bottom_of_the_full_cover_only():
    from freecad.PartReview.domain.models import ReportLevel
    logo = '<img class="logo"'
    for level, at_bottom in ((ReportLevel.FULL, True), (ReportLevel.STANDARD, True),
                             (ReportLevel.QUICK, False)):
        inputs = make_inputs()
        inputs.config.level = level
        uris = ["data:image/png;base64,A%d" % i for i in range(len(inputs.boundary_views) + len(inputs.views))]
        page = render_html(build_report(inputs, Translator("pt_BR", strict=True)), uris,
                           logo_uri="data:image/png;base64,LOGO")
        assert page.count(logo) == 1
        assert (page.index(logo) > page.index("<h1>")) is at_bottom, level
        assert ('class="logo-center"' in page) is at_bottom


def test_html_uses_legible_shades_of_a_light_accent():
    inputs = make_inputs()
    inputs.config.accent_color = "#ffff00"
    uris = ["data:image/png;base64,A%d" % i for i in range(len(inputs.boundary_views) + len(inputs.views))]
    page = render_html(build_report(inputs, Translator("pt_BR", strict=True)), uris)
    assert "h1{color:#7a7a00" in page  # titles: darker shade, 4.5:1 on white
    assert "border-top:10px solid #ffff00" in page  # decorative band: exact color
