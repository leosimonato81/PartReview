# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
#
# Generate a FEM report without the dialog.
#
# Inside FreeCAD (Python console), with the FEM document open:
#   exec(open("<repo>/tests/freecad/run_report_headless.py", encoding="utf-8").read())
#
# Invisible GUI run (used by Claude), environment variables:
#   PARTREVIEW_DOC   path of the .FCStd to open
#   PARTREVIEW_OUT   output PDF path
#   PARTREVIEW_LANG  pt_BR (default) or en
#   PARTREVIEW_YIELD optional yield strength, e.g. "250 MPa"
#   PARTREVIEW_REQUIRED_FS optional required safety factor, e.g. "2"
#   PARTREVIEW_UNITS mpa_mm (default) or freecad_schema
#   PARTREVIEW_TITLE optional report title
#   PARTREVIEW_LEVEL quick, standard or full (default)
#   PARTREVIEW_COMPANY / PARTREVIEW_LOGO / PARTREVIEW_AUTHOR optional cover data
#   PARTREVIEW_ACCENT optional accent color "#rrggbb" (empty = default)
#   PARTREVIEW_EXPORTS "csv,html" to also write those files
#   PARTREVIEW_BOUNDARY "1" to include the supports-and-loads figure (beta, off by default)
#   PARTREVIEW_RESULT  internal name of the result to use (default: the first)
#   PARTREVIEW_EXIT  "1" to quit FreeCAD at the end
#   e.g. flatpak run --env=QT_QPA_PLATFORM=offscreen --env=PARTREVIEW_EXIT=1 ... \
#        org.freecad.FreeCAD <repo>/tests/freecad/run_report_headless.py

import os
import sys
import time
import traceback

import FreeCAD as App
import FreeCADGui as Gui

for _name in [n for n in sys.modules if n.startswith("freecad.PartReview")]:
    del sys.modules[_name]

from freecad.PartReview.adapters import fem_reader  # noqa: E402
from freecad.PartReview.adapters.report_job import generate_fem_report  # noqa: E402
from freecad.PartReview.domain.models import ReportConfig, ReportLevel, UnitSystem  # noqa: E402


def main():
    path = os.environ.get("PARTREVIEW_DOC")
    doc = App.openDocument(path) if path else App.ActiveDocument
    Gui.updateGui()
    if doc is None:
        print("run_report_headless: open a document first")
        return
    results = fem_reader.list_mechanical_results(doc)
    print("mechanical results:", results)
    if not results:
        print("run_report_headless: no mechanical results")
        return
    default_out = os.path.splitext(doc.FileName)[0] + "_PartReview.pdf"
    config = ReportConfig(
        result_name=os.environ.get("PARTREVIEW_RESULT", results[0][0]),
        language=os.environ.get("PARTREVIEW_LANG", "pt_BR"),
        output_path=os.environ.get("PARTREVIEW_OUT", default_out),
        yield_strength=os.environ.get("PARTREVIEW_YIELD", ""),
        required_safety=os.environ.get("PARTREVIEW_REQUIRED_FS", ""),
        unit_system=UnitSystem(os.environ.get("PARTREVIEW_UNITS", "mpa_mm")),
        title=os.environ.get("PARTREVIEW_TITLE", ""),
        level=ReportLevel(os.environ.get("PARTREVIEW_LEVEL", "full")),
        company=os.environ.get("PARTREVIEW_COMPANY", ""),
        logo_path=os.environ.get("PARTREVIEW_LOGO", ""),
        accent_color=os.environ.get("PARTREVIEW_ACCENT", ""),
        author=os.environ.get("PARTREVIEW_AUTHOR", ""),
        export_csv="csv" in os.environ.get("PARTREVIEW_EXPORTS", ""),
        export_html="html" in os.environ.get("PARTREVIEW_EXPORTS", ""),
        show_boundary=os.environ.get("PARTREVIEW_BOUNDARY") == "1",
    )
    modified_before = Gui.getDocument(doc.Name).Modified
    vis_before = {o.Name: o.ViewObject.Visibility for o in doc.Objects if o.ViewObject}
    start = time.perf_counter()

    def progress(message, fraction):
        if message:
            print("[%3d%%] %s (%.1f s)" % (fraction * 100, message, time.perf_counter() - start))

    written = generate_fem_report(doc, config, progress)
    vis_after = {o.Name: o.ViewObject.Visibility for o in doc.Objects if o.ViewObject}
    changed = [n for n in vis_before if vis_before[n] != vis_after.get(n)]
    for path in written:
        print("written:", path)
    print("time: %.1f s" % (time.perf_counter() - start))
    print("visibility changed after report:", changed or "none")
    print("modified flag before/after:", modified_before, Gui.getDocument(doc.Name).Modified)


log_path = os.environ.get("PARTREVIEW_LOG")
if log_path:
    sys.stdout = open(log_path, "w", encoding="utf-8")
try:
    main()
except Exception:
    traceback.print_exc(file=sys.stdout)
finally:
    sys.stdout.flush()
    if os.environ.get("PARTREVIEW_EXIT") == "1":
        os._exit(0)
