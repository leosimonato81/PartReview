# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""CSV of nodal values and HTML of the report (phase 6a, step h).

Pure Python (stdlib only). The HTML is built from the same Document blocks as
the PDF, so new sections (DFM, combined risks) appear in both without extra
work. Images arrive as ready-to-use URIs (data: URIs from the adapter).
"""

import csv
import html
import io

from . import colormap
from .blocks import BarChart, BulletList, Figure, Heading, Notice, Paragraph, Table
from .colors import accent_palette, to_hex
from .i18n import Translator
from .models import FieldKind, FemResult

CSV_FIELDS = (FieldKind.VON_MISES, FieldKind.DISPLACEMENT, FieldKind.ESTIMATED_ERROR)


def nodal_csv(result: FemResult, tr: Translator, extra_fields=()) -> str:
    """One row per node: id, coordinates and every available field, with units.

    pt_BR uses ';' and decimal comma (spreadsheet convention in Brazil);
    en uses ',' and decimal point.
    """
    fields = dict(result.fields)
    for f in extra_fields:
        fields[f.kind] = f
    columns = [k for k in CSV_FIELDS if k in fields]
    values = {k: dict(zip(fields[k].node_ids, fields[k].values)) for k in columns}
    unit = result.mesh.length_unit
    header = [tr.t("csv.node")] + ["%s [%s]" % (axis, unit) for axis in ("x", "y", "z")]
    header += ["%s [%s]" % (tr.t("field." + k.value), fields[k].unit) for k in columns]
    sep = ";" if tr.decimal_sep == "," else ","

    def num(value):
        return repr(float(value)).replace(".", tr.decimal_sep)

    out = io.StringIO()
    writer = csv.writer(out, delimiter=sep, lineterminator="\n")
    writer.writerow(header)
    for node in sorted(result.mesh.node_positions):
        p = result.mesh.node_positions[node]
        row = [str(node), num(p.x), num(p.y), num(p.z)]
        row += [num(values[k][node]) if node in values[k] else "" for k in columns]
        writer.writerow(row)
    return out.getvalue()


# --- HTML ------------------------------------------------------------------------

def _e(text) -> str:
    return html.escape(str(text), quote=True)


def _css(accent) -> str:
    # Same WCAG-checked shades as the PDF (domain/colors.py).
    palette = accent_palette(accent)
    stops = ", ".join("rgb(%d,%d,%d) %d%%" % (int(c[0] * 255), int(c[1] * 255), int(c[2] * 255),
                                              round(pos * 100)) for pos, c in colormap.STOPS)
    return """
body{font-family:"DejaVu Sans",Arial,sans-serif;color:#1e1e1e;max-width:980px;margin:2em auto;
padding:0 1.2em;line-height:1.45}
h1{color:%(t)s;font-size:2em;margin-bottom:.2em}h2{color:%(t)s;border-bottom:2px solid %(c)s;
padding-bottom:.15em;margin-top:2em}
.cover{border-top:10px solid %(b)s;padding-top:1em}.cover .company{float:right;font-weight:bold}
.cover img.logo{max-height:90px;max-width:240px}.logo-center{clear:both;text-align:center;
margin:1em 0}.subtitle{color:#6e6e6e;font-size:1.1em}
table{border-collapse:collapse;width:100%%;margin:.6em 0 1em}td,th{border-bottom:1px solid #ccc;
padding:.35em .5em;text-align:left;vertical-align:top;white-space:pre-line}
th{background:%(l)s}.kv td:first-child{color:#555;width:34%%}
.notice{border-left:5px solid #d68200;padding:.4em .8em;margin:.6em 0;background:#fff8ec}
.notice.info{border-color:#286ebe;background:#f1f6fc}
figure{margin:1.2em 0}.fig{display:flex;gap:1em;align-items:stretch}
.fig img{width:80%%;border:1px solid #ccc}.legend{display:flex;flex-direction:column;font-size:.8em}
.legend .sw{display:inline-block;width:14px;height:14px;border:1px solid #888;vertical-align:middle}.legend .bar{display:flex;flex:1;gap:.4em;min-height:200px}.legend .grad{width:16px;
background:linear-gradient(to top,%(s)s);border:1px solid #888}.legend .ticks{display:flex;
flex-direction:column-reverse;justify-content:space-between}
figcaption{color:#6e6e6e;font-style:italic;font-size:.9em;white-space:pre-line}
.chart{display:flex;align-items:flex-end;gap:4px;height:180px;border-left:1px solid #888;
border-bottom:1px solid #888;padding:0 4px}.chart div{flex:1;background:%(c)s;position:relative}
.chart span{position:absolute;top:-1.3em;width:100%%;text-align:center;font-size:.75em;color:#333}
.chart-labels{display:flex;gap:4px;padding:0 4px;font-size:.75em;color:#666}
.chart-labels div{flex:1;text-align:center}footer{margin-top:3em;color:#888;font-size:.85em}
""" % {"c": to_hex(palette.graphic), "t": to_hex(palette.text), "b": to_hex(palette.base),
       "l": to_hex(palette.light), "s": stops}


def _table(block: Table) -> str:
    cls = ' class="kv"' if not block.header else ""
    parts = ["<table%s>" % cls]
    if block.header:
        parts.append("<tr>%s</tr>" % "".join("<th>%s</th>" % _e(h) for h in block.header))
    for row in block.rows:
        parts.append("<tr>%s</tr>" % "".join("<td>%s</td>" % _e(c) for c in row))
    parts.append("</table>")
    return "".join(parts)


def _figure(block: Figure, image_uris) -> str:
    caption = _e(block.caption) + ("\n" + _e(block.balloons) if block.balloons else "")
    if block.legend.swatches:  # category legend: one colored square per entry
        key = "".join('<div><span class="sw" style="background:rgb(%d,%d,%d)"></span> %s</div>'
                      % (r, g, b, _e(label)) for (r, g, b), label in block.legend.swatches)
    else:
        ticks = "".join("<span>%s</span>" % _e(label) for _, label in block.legend.ticks)
        key = ('<div class="bar"><div class="grad"></div><div class="ticks">%s</div></div>'
               % ticks)
    return ('<figure><div class="fig"><img src="%s" alt="%s"><div class="legend"><b>%s</b>'
            '%s</div></div><figcaption>%s</figcaption></figure>'
            % (image_uris[block.view_index], _e(block.caption), _e(block.legend.title), key,
               caption))


def _chart(block: BarChart) -> str:
    peak = max(block.values) if block.values and max(block.values) > 0 else 1.0
    bars = "".join('<div style="height:%.1f%%"><span>%d</span></div>' % (100 * v / peak, v)
                   for v in block.values)
    labels = "".join("<div>%s</div>" % _e(lbl) for lbl in block.labels)
    return ('<figure><b>%s</b><div class="chart">%s</div><div class="chart-labels">%s</div>'
            '<figcaption>%s</figcaption></figure>' % (_e(block.title), bars, labels,
                                                      _e(block.caption)))


def render_html(doc, image_uris, logo_uri: str = "", language: str = "pt_BR") -> str:
    cover = doc.cover
    parts = ['<!DOCTYPE html><html lang="%s"><head><meta charset="utf-8">' % _e(
        language.replace("_", "-")), "<title>%s</title>" % _e(doc.title),
        "<style>%s</style></head><body>" % _css(doc.accent), '<header class="cover">']
    if cover.company:
        parts.append('<div class="company">%s</div>' % _e(cover.company))
    logo = '<img class="logo" src="%s" alt="logo">' % logo_uri if logo_uri else ""
    if logo and not cover.full_page:  # quick summary: logo next to the title, as before
        parts.append(logo)
    parts.append("<h1>%s</h1>" % _e(cover.title))
    if cover.subtitle:
        parts.append('<div class="subtitle">%s</div>' % _e(cover.subtitle))
    rows = list(cover.info) + ([(cover.level_caption, cover.level_label)]
                               if cover.level_label else [])
    parts.append(_table(Table((), tuple(rows), (0.3, 0.7))))
    if logo and cover.full_page:  # full cover: centered at the bottom (same as the PDF)
        parts.append('<div class="logo-center">%s</div>' % logo)
    parts.append("</header>")
    if doc.toc:
        parts.append("<nav><h2>%s</h2><ol>" % _e(doc.toc_title))
        parts += ['<li><a href="#%s">%s</a></li>' % (_e(e.anchor), _e(e.title)) for e in doc.toc]
        parts.append("</ol></nav>")
    for block in doc.blocks:
        if isinstance(block, Heading):
            parts.append('<h2 id="%s">%s</h2>' % (_e(block.anchor), _e(block.text)))
        elif isinstance(block, Paragraph):
            parts.append("<p>%s</p>" % _e(block.text))
        elif isinstance(block, Notice):
            cls = "notice" if block.level == "warning" else "notice info"
            parts.append('<div class="%s">%s</div>' % (cls, _e(block.text)))
        elif isinstance(block, BulletList):
            parts.append("<ul>%s</ul>" % "".join("<li>%s</li>" % _e(i) for i in block.items))
        elif isinstance(block, Table):
            parts.append(_table(block))
        elif isinstance(block, Figure):
            parts.append(_figure(block, image_uris))
        elif isinstance(block, BarChart):
            parts.append(_chart(block))
    parts.append("<footer>%s</footer></body></html>" % _e(doc.footer))
    return "\n".join(parts)
