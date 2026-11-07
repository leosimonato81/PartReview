# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
#
# Compatibility case 8: does generating a report change the saved file?
#
# Copies the model twice to a temporary folder, saves copy A as is and copy B
# after generating a report, then compares what FreeCAD stored:
# Document.xml (objects, properties, flags), GuiDocument.xml (view
# properties, camera) and the geometry. Prints PASS or the differences.
# Differences that also appear between two plain saves (FreeCAD itself) are
# ignored: order of entries, numbering of attachments, mesh file order.
#
# Run with the FreeCAD GUI (visible or offscreen), model given by
#   PARTREVIEW_DOC=<path to .FCStd>   [PARTREVIEW_LOG, PARTREVIEW_EXIT=1]
# Inside FreeCAD's Python console:
#   import os; os.environ["PARTREVIEW_DOC"] = "/path/model.FCStd"
#   exec(open("<repo>/tests/freecad/check_saved_file.py", encoding="utf-8").read())

import os
import re
import shutil
import sys
import tempfile
import traceback
import xml.etree.ElementTree as ET
import zipfile

import FreeCAD as App
import FreeCADGui as Gui

for _name in [n for n in sys.modules if n.startswith("freecad.PartReview")]:
    del sys.modules[_name]

from freecad.PartReview.adapters import fem_reader  # noqa: E402
from freecad.PartReview.adapters.report_job import generate_fem_report  # noqa: E402
from freecad.PartReview.domain.models import ReportConfig  # noqa: E402


def document_xml(zf):
    text = zf.read("Document.xml").decode("utf-8")
    # file name and save dates differ by construction
    return [line for line in text.splitlines()
            if not re.search(r'value="\d{4}-\d\d-\d\dT|FileName|<String value="[AB]"/>', line)]


def gui_state(zf):
    root = ET.fromstring(zf.read("GuiDocument.xml"))
    props = {(vp.get("name"), p.get("name")): (
        p.get("status"), [(c.tag, {k: v for k, v in c.attrib.items() if k != "file"}) for c in p])
        for vp in root.iter("ViewProvider") for p in vp.iter("Property")}
    cams = [c.get("settings") for c in root.iter("Camera")]
    return props, cams


def attachments(zf, prefixes=("NodeColorArray", "ElementColorArray", "ShapeAppearance")):
    return sorted(zf.read(n) for n in zf.namelist() if n.startswith(prefixes))


def geometry(zf):
    return {n: zf.read(n) for n in zf.namelist() if n.endswith(".brp")}


def main():
    source = os.environ.get("PARTREVIEW_DOC") or (App.ActiveDocument and App.ActiveDocument.FileName)
    work = tempfile.mkdtemp(prefix="partreview_save_")
    a, b = os.path.join(work, "A.FCStd"), os.path.join(work, "B.FCStd")
    shutil.copy(source, a)
    shutil.copy(source, b)

    doc = App.openDocument(a)
    Gui.updateGui()
    doc.save()
    App.closeDocument(doc.Name)

    doc = App.openDocument(b)
    Gui.updateGui()
    result = fem_reader.list_mechanical_results(doc)[0][0]
    generate_fem_report(doc, ReportConfig(result_name=result,
                                          output_path=os.path.join(work, "B.pdf")))
    Gui.updateGui()
    doc.save()
    App.closeDocument(doc.Name)

    za, zb = zipfile.ZipFile(a), zipfile.ZipFile(b)
    problems = []
    if document_xml(za) != document_xml(zb):
        problems.append("Document.xml (objects/properties/flags) differs")
    pa, ca = gui_state(za)
    pb, cb = gui_state(zb)
    changed = [k for k in set(pa) | set(pb) if pa.get(k) != pb.get(k)]
    if changed:
        problems.append("view properties differ: %s" % changed[:10])
    if ca != cb:
        problems.append("camera differs")
    if attachments(za) != attachments(zb):
        problems.append("colour/appearance attachments differ")
    if geometry(za) != geometry(zb):
        problems.append("geometry (.brp) differs")
    print("model:", source)
    print("work folder:", work)
    if problems:
        print("SAVED FILE CHANGED:")
        for p in problems:
            print("  -", p)
    else:
        print("PASS: the file saved after a report matches a plain save "
              "(known cosmetic difference: model-tree order attributes 'treeRank')")


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
