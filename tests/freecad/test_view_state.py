# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
#
# Integration test for adapters/view_state.py (CLAUDE.md rule 3).
# Changes the view inside a ViewState, raises an error on purpose, then checks
# that visibility, transparency, culling, mesh colors, camera and the
# document's modified flag are exactly as before. Prints "VIEWSTATE OK" or the
# differences.
#
# Inside FreeCAD (Python console), with a FEM document open:
#   exec(open("<repo>/tests/freecad/test_view_state.py", encoding="utf-8").read())
# Invisible run: same env variables as run_report_headless.py
#   (PARTREVIEW_DOC, PARTREVIEW_LOG, PARTREVIEW_EXIT).

import os
import sys
import traceback

import FreeCAD as App
import FreeCADGui as Gui

for _name in [n for n in sys.modules if n.startswith("freecad.PartReview")]:
    del sys.modules[_name]

from freecad.PartReview.adapters import fem_reader  # noqa: E402
from freecad.PartReview.adapters.view_state import ViewState  # noqa: E402
from freecad.PartReview.domain import camera_planner as cp  # noqa: E402
from freecad.PartReview.domain.models import Vec3  # noqa: E402


class Boom(Exception):
    pass


def snapshot(doc, gui_doc):
    state = {"camera": gui_doc.ActiveView.getCamera(), "modified": gui_doc.Modified}
    for obj in doc.Objects:
        vo = obj.ViewObject
        if vo is None:
            continue
        props = vo.PropertiesList
        state[obj.Name] = (
            vo.Visibility,
            vo.Transparency if "Transparency" in props else None,
            vo.BackfaceCulling if "BackfaceCulling" in props else None,
            vo.ColorMode if "ColorMode" in props else None,
            len(vo.NodeColorArray) if "NodeColorArray" in props else None,
        )
    return state


def main():
    path = os.environ.get("PARTREVIEW_DOC")
    doc = App.openDocument(path) if path else App.ActiveDocument
    Gui.updateGui()
    gui_doc = Gui.getDocument(doc.Name)
    result = doc.getObject(fem_reader.list_mechanical_results(doc)[0][0])
    mesh = result.Mesh

    before = snapshot(doc, gui_doc)
    scene = gui_doc.ActiveView.getSceneGraph()
    children_before = scene.getNumChildren()
    try:
        with ViewState(doc) as vs:
            vs.show_only([mesh])
            vs.set_backface_culling(mesh, False)
            ids = list(result.NodeNumbers)
            vs.color_nodes(mesh, ids, [(-1.0 if i % 2 else 1.0) for i in range(len(ids))])
            vs.apply_camera(cp.frame(Vec3(1, 1, -1), Vec3(0, 0, 0), 10.0, Vec3(0, 0, 0), 50.0))
            from pivy import coin
            vs.displace(mesh, ids, [v for v in result.DisplacementVectors], 1000.0)  # deformed
            vs.add_overlay(coin.SoSeparator())  # temporary drawing (outline, supports/loads)
            raise Boom("error on purpose in the middle of a capture")
    except Boom:
        print("error raised and propagated: yes")
    after = snapshot(doc, gui_doc)

    diffs = [k for k in before if before[k] != after.get(k)]
    if scene.getNumChildren() != children_before:
        diffs.append("scene graph children")
        before["scene graph children"] = children_before
        after["scene graph children"] = scene.getNumChildren()
    if diffs:
        print("VIEWSTATE FAILED, differences:")
        for k in diffs:
            print("  %s: before=%r after=%r" % (k, before[k], after.get(k)))
    else:
        print("VIEWSTATE OK: %d objects, camera and modified flag restored" % (len(before) - 2))


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
