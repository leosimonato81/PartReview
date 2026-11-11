# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
#
# adapters/mesh_check.py and the single-threaded GmshJob, in FreeCAD (no GUI).
#
#   flatpak run --command=freecadcmd --filesystem=<repo> --filesystem=$T \
#     --env=PARTREVIEW_REPO=<repo> --env=PARTREVIEW_OUT=$T/mesh_check.txt \
#     org.freecad.FreeCAD --user-cfg $T/<copy of user.cfg> \
#     -c "exec(open('<repo>/tests/freecad/test_mesh_check.py').read())"
# Writes PASS/FAIL lines; the last line is "ALL PASS" or "FAILED: n".
# Memory: one 20x10x5 mm box, a few hundred nodes (Gmsh watched as usual).

import os
import sys
import tempfile
import time

import FreeCAD as App
import Fem
import ObjectsFem
import Part

REPO = os.environ.get("PARTREVIEW_REPO") or os.getcwd()
sys.path.insert(0, REPO)
for name in [n for n in sys.modules if n.startswith("freecad.PartReview")]:
    del sys.modules[name]

from freecad.PartReview.adapters import mesh_runner  # noqa: E402
from freecad.PartReview.adapters.mesh_check import degenerate_elements  # noqa: E402

OUT = open(os.environ.get("PARTREVIEW_OUT", os.path.join(tempfile.gettempdir(),
                                                         "mesh_check.txt")), "w")
failures = []


def check(name, condition, detail=""):
    OUT.write("%s %s %s\n" % ("PASS" if condition else "FAIL", name, detail))
    OUT.flush()
    if not condition:
        failures.append(name)


MIDS = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))


def add_tet10(mesh, corners, first_node, eid, move=None):
    """Straight-sided 10-node tetrahedron; ``move`` = (mid-side index 0..5, vector)."""
    pts = [App.Vector(*c) for c in corners]
    pts += [(pts[a] + pts[b]) * 0.5 for a, b in MIDS]
    if move is not None:
        pts[4 + move[0]] = pts[4 + move[0]] + App.Vector(*move[1])
    ids = list(range(first_node, first_node + 10))
    for nid, p in zip(ids, pts):
        mesh.addNode(p.x, p.y, p.z, nid)
    mesh.addVolume(ids, eid)


GOOD = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
FLAT = [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]  # four corners in the plane y = 0

m = Fem.FemMesh()
add_tet10(m, GOOD, 1, 1)
add_tet10(m, [(x + 3, y, z) for x, y, z in GOOD], 11, 2)
add_tet10(m, FLAT, 21, 3)
add_tet10(m, [(x + 6, y, z) for x, y, z in GOOD], 31, 4, move=(0, (0.0, 0.0, 1.2)))  # folded
found = degenerate_elements(m)
check("tet10: good elements pass, flat and folded are found", sorted(found) == [3, 4],
      str(found))

m4 = Fem.FemMesh()
for nid, p in enumerate(GOOD + [(x + 3, y, z) for x, y, z in GOOD]
                        + [(x + 6, y, z) for x, y, z in GOOD], start=1):
    m4.addNode(p[0], p[1], p[2], nid)
m4.addVolume([1, 2, 3, 4], 1)
m4.addVolume([5, 6, 7, 8], 2)
m4.addVolume([9, 11, 10, 12], 3)  # two corners swapped: inverted
check("tet4: inverted element found", degenerate_elements(m4) == [3],
      str(degenerate_elements(m4)))

# GmshJob: single thread written into the .geo, mesh loaded and checked.
doc = App.newDocument("MeshCheck")
doc.UndoMode = 1  # off by default without the GUI
box = doc.addObject("Part::Feature", "Box")
box.Shape = Part.makeBox(20, 10, 5)
mesh = ObjectsFem.makeMeshGmsh(doc, "Mesh")
mesh.Shape = box
mesh.CharacteristicLengthMax = 2.5
mesh.ElementOrder = "2nd"
doc.recompute()
job = mesh_runner.GmshJob(mesh, 60, 1000, load_into_object=True)
geo = open(job.tools.temp_file_geo).read()
check("GmshJob writes General.NumThreads = 1",
      "General.NumThreads = 1;" in geo and geo.count("NumThreads") == 1)
job.start()
while job.poll() == job.RUNNING:
    time.sleep(0.1)
check("GmshJob meshes and loads", job.state == job.DONE and mesh.FemMesh.NodeCount > 0,
      "%s, %d nodes" % (job.state, mesh.FemMesh.NodeCount))
check("GmshJob finds no degenerate element on a box", job.degenerate == (),
      str(job.degenerate[:5]))
check("GmshJob load is one undo step",
      doc.UndoCount == 1 and doc.UndoNames == ["PartReview: generate mesh"],
      "%d %s" % (doc.UndoCount, doc.UndoNames))
App.closeDocument(doc.Name)

OUT.write("ALL PASS\n" if not failures else "FAILED: %d\n" % len(failures))
OUT.close()
