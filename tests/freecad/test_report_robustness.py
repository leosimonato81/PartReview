# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
#
# v1.6.3 fixes, invisible GUI, on a COPY of examples/viga_em_balanco.FCStd:
# 1. A result mesh without tetrahedra (seen on Windows, FreeCAD 1.1.3:
#    "'NoneType' object has no attribute 'triangles'" while capturing the deformed
#    view): the tetrahedra come from the analysis mesh when it has the same nodes;
#    without any tetrahedra the report is still written (no surface, no outline).
# 2. Output folder: Downloads by default; a folder the user chose is remembered.
#
#   flatpak run --env=QT_QPA_PLATFORM=offscreen --filesystem=<repo> --filesystem=$T \
#     --env=PARTREVIEW_REPO=<repo> --env=PARTREVIEW_OUT=$T/robustness.txt \
#     org.freecad.FreeCAD --user-cfg $T/<copy of user.cfg> \
#     <repo>/tests/freecad/test_report_robustness.py
# Writes PASS/FAIL lines; the last line is "ALL PASS" or "FAILED: n".
# Memory: the example has ~5 000 nodes; no mesher, no solver.

import os
import shutil
import sys
import tempfile
import traceback

import FreeCAD as App
import Fem

REPO = os.environ.get("PARTREVIEW_REPO") or os.getcwd()
OUT = open(os.environ.get("PARTREVIEW_OUT", os.path.join(tempfile.gettempdir(),
                                                         "robustness.txt")), "w")
failures = []


def check(name, condition, detail=""):
    OUT.write("%s %s %s\n" % ("PASS" if condition else "FAIL", name, detail))
    OUT.flush()
    if not condition:
        failures.append(name)


def main():
    sys.path.insert(0, REPO)
    for name in [n for n in sys.modules if n.startswith("freecad.PartReview")]:
        del sys.modules[name]
    from freecad.PartReview.adapters import fem_reader, preferences, report_job
    from freecad.PartReview.domain.models import ReportConfig, ReportLevel

    work = tempfile.mkdtemp(prefix="pr_robust_")
    preferences._file = lambda: os.path.join(work, "last_report.json")  # never the user's
    copy = os.path.join(work, "viga.FCStd")
    shutil.copy(os.path.join(REPO, "examples", "viga_em_balanco.FCStd"), copy)
    doc = App.openDocument(copy)
    result = doc.getObject("CCX_Results")
    original = result.Mesh.FemMesh.copy()

    # 1a. result mesh with the same nodes but only face elements (no volume):
    # tetrahedra taken from the analysis mesh
    faces_only = Fem.FemMesh()
    for nid, p in original.Nodes.items():
        faces_only.addNode(p.x, p.y, p.z, nid)
    solver_mesh = doc.getObject("Mesh").FemMesh
    for fid in solver_mesh.Faces:
        faces_only.addFace(list(solver_mesh.getElementNodes(fid)), fid)
    result.Mesh.FemMesh = faces_only
    check("test mesh: faces, no volumes", faces_only.VolumeCount == 0 and faces_only.FaceCount > 0,
          "%d faces" % faces_only.FaceCount)
    read = fem_reader.read_fem_result(doc, "CCX_Results")
    check("no volumes in the result mesh: tetrahedra taken from the analysis mesh",
          len(read.elements) == original.VolumeCount, "%d elements" % len(read.elements))

    def report(level, name):
        config = ReportConfig(result_name="CCX_Results", language="en",
                              output_path=os.path.join(work, name), level=level)
        return report_job.generate_fem_report(doc, config)

    for level in (ReportLevel.QUICK, ReportLevel.FULL):
        written = report(level, "fallback_%s.pdf" % level.value)
        check("report %s with the fallback" % level.value,
              written and os.path.getsize(written[0]) > 10000)

    # 1b. no tetrahedra at all (fallback refused): report without surface, no crash
    real = fem_reader.result_volume_elements
    fem_reader.result_volume_elements = lambda mesh_obj, analysis: ()
    try:
        for level in (ReportLevel.QUICK, ReportLevel.FULL):
            try:
                written = report(level, "nosurface_%s.pdf" % level.value)
                check("report %s without any tetrahedra" % level.value,
                      written and os.path.getsize(written[0]) > 10000)
            except Exception:
                check("report %s without any tetrahedra" % level.value, False,
                      traceback.format_exc().replace("\n", " | ")[-400:])
    finally:
        fem_reader.result_volume_elements = real
    result.Mesh.FemMesh = original
    App.closeDocument(doc.Name)

    # 2. output folder
    downloads = preferences.downloads_dir()
    check("default folder is Downloads (or home when there is none)",
          preferences.output_dir() == downloads and os.path.isdir(downloads), downloads)
    logo = preferences.freecad_logo_path()
    elsewhere = os.path.join(work, "reports")
    os.makedirs(elsewhere)
    config = ReportConfig(result_name="x", output_path=os.path.join(elsewhere, "a.pdf"),
                          logo_path=logo)
    preferences.remember_report_fields(config)
    check("a folder chosen by the user is remembered", preferences.output_dir() == elsewhere,
          preferences.output_dir())
    preferences._session = None  # what a FreeCAD restart forgets ...
    check("... and survives a restart (file)", preferences.output_dir() == elsewhere)
    config.output_path = os.path.join(downloads, "b.pdf")
    preferences.remember_report_fields(config)
    check("back to Downloads: nothing left to remember (file removed)",
          preferences.output_dir() == downloads
          and not os.path.exists(preferences._file()))
    config.output_path = os.path.join(elsewhere, "c.pdf")
    config.logo_path = ""
    preferences.remember_report_fields(config)
    shutil.rmtree(elsewhere)
    check("remembered folder deleted: back to Downloads, logo still remembered",
          preferences.output_dir() == downloads and preferences.remembered_logo() == "")


try:
    main()
except Exception:
    OUT.write(traceback.format_exc())
    failures.append("exception")
for name in list(App.listDocuments()):
    App.closeDocument(name)
OUT.write("ALL PASS\n" if not failures else "FAILED: %d\n" % len(failures))
OUT.close()
os._exit(0)
