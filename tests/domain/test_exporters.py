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
    uris = ["data:image/png;base64,AAA%d" % i for i in range(len(inputs.views))]
    page = render_html(doc, uris, logo_uri="data:image/png;base64,LOGO")
    assert page.startswith("<!DOCTYPE html>") and 'lang="pt-BR"' in page
    assert "&lt;Oficina &amp; Cia&gt;" in page and "<Oficina" not in page
    for entry in doc.toc:
        assert 'href="#%s"' % entry.anchor in page and 'id="%s"' % entry.anchor in page
    assert page.count("<figure>") >= len(inputs.views)
    assert "http" not in page.replace("https://", "")  # no external resources
