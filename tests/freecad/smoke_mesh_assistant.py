# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
#
# Smoke test of the mesh assistant on a COPY of a document, invisible GUI:
# analyse the part, test the options (Gmsh + CalculiX probes), ask for an
# objective, create the recommended mesh, and print what the panel shows.
#
#   flatpak run --env=QT_QPA_PLATFORM=offscreen --env=PARTREVIEW_DOC=<file.FCStd> \
#       --env=PARTREVIEW_PART=<object name> --env=PARTREVIEW_OUT=<report.txt> \
#       org.freecad.FreeCAD --user-cfg <copy of user.cfg> <repo>/tests/freecad/smoke_mesh_assistant.py
#
# The machine calibration is written to a temporary file, never to the user's.

import os
import shutil
import sys
import tempfile
import time
import traceback

import FreeCAD as App
import FreeCADGui as Gui
from PySide6.QtWidgets import QApplication

OUT = open(os.environ.get("PARTREVIEW_OUT", os.path.join(tempfile.gettempdir(),
                                                        "smoke_assistant.txt")), "w")


def say(*parts):
    OUT.write(" ".join(str(p) for p in parts) + "\n")
    OUT.flush()


def wait(panel, limit=900):
    started = time.time()
    while time.time() - started < limit:
        QApplication.processEvents()
        time.sleep(0.05)
        if panel.job is None and not panel.tasks:
            return True
    return False


def table(panel):
    for r in range(panel.table.rowCount()):
        cells = [panel.table.item(r, c).text() if panel.table.item(r, c) else ""
                 for c in range(panel.table.columnCount())]
        say("   |", " | ".join(cells))


def main():
    for name in [n for n in sys.modules if n.startswith("freecad.PartReview")]:
        del sys.modules[name]
    Gui.activateWorkbench("PartReviewWorkbench")
    from freecad.PartReview.adapters import machine_calibration
    calibration = os.path.join(tempfile.mkdtemp(prefix="pr_calib_"), "calibration.json")
    machine_calibration._file = lambda: calibration
    from freecad.PartReview.ui import mesh_assistant as ma
    ma.QMessageBox.information = lambda *a: say("  message:", a[2][:200])

    source = os.environ["PARTREVIEW_DOC"]
    copy = os.path.join(tempfile.mkdtemp(prefix="pr_smoke_"), os.path.basename(source))
    shutil.copy(source, copy)
    doc = App.openDocument(copy)
    part = doc.getObject(os.environ.get("PARTREVIEW_PART", ""))
    if part is not None:
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(part)
    panel = ma.MeshAssistantPanel(doc)
    Gui.Control.showDialog(panel)
    QApplication.processEvents()
    say("part:", panel.part_combo.currentText())
    if panel.summary is None:
        panel.analyze()
    for title, value in panel.machine_rows:
        say("  computer:", title.text(), "=", value.text())
    say("refine:", panel.refine_label.text())
    for i in range(panel.issues.count()):
        say("  issue:", panel.issues.item(i).text()[:160])

    started = time.time()
    panel.test_options()
    finished = wait(panel)
    say("test options: %s in %.0f s -> %s" % ("done" if finished else "TIMEOUT",
                                            time.time() - started, panel.status_label.text()))
    say("recommend:", panel.recommend_label.text().replace("\n", " "))
    table(panel)

    panel.objective_box.setCurrentIndex(0)  # fits the memory
    started = time.time()
    panel.auto_mesh()
    wait(panel)
    say("objective %r (%.0f s): %s" % (panel.objective_box.currentText(),
                                       time.time() - started, panel.status_label.text()))

    panel._select_level(panel.recommended[0])
    panel.create_mesh()
    started = time.time()
    while time.time() - started < 300 and Gui.Control.activeDialog():
        QApplication.processEvents()
        time.sleep(0.05)
    meshes = [o for o in doc.Objects if o.isDerivedFrom("Fem::FemMeshObject")
              and hasattr(o, "PartReviewAssistant")]
    say("created:", [(m.Label, m.FemMesh.NodeCount) for m in meshes])
    say("in analysis:", [o.Label for a in doc.Objects if a.isDerivedFrom("Fem::FemAnalysis")
                         for o in a.Group if o in meshes])
    say("panel closed:", not bool(Gui.Control.activeDialog()))
    say("undo:", doc.UndoNames[:3])


try:
    main()
except Exception:
    say(traceback.format_exc())
for name in list(App.listDocuments()):
    App.closeDocument(name)
OUT.close()
os._exit(0)
