# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
#
# adapters/fem_reader.materials_of_part + domain/materials (A6), in FreeCAD (no GUI).
# No mesh, no solver: only document objects.
#
#   flatpak run --command=freecadcmd --filesystem=<repo> --filesystem=$T \
#     --env=PARTREVIEW_REPO=<repo> --env=PARTREVIEW_OUT=$T/material_notes.txt \
#     org.freecad.FreeCAD --user-cfg $T/<copy of user.cfg> \
#     -c "exec(open('<repo>/tests/freecad/test_material_notes.py').read())"
# Writes PASS/FAIL lines; the last line is "ALL PASS" or "FAILED: n".

import os
import sys
import tempfile

import FreeCAD as App
import ObjectsFem
import Part

REPO = os.environ.get("PARTREVIEW_REPO") or os.getcwd()
sys.path.insert(0, REPO)
for name in [n for n in sys.modules if n.startswith("freecad.PartReview")]:
    del sys.modules[name]

from freecad.PartReview.adapters.fem_reader import materials_of_part  # noqa: E402
from freecad.PartReview.domain.i18n import Translator  # noqa: E402
from freecad.PartReview.domain.materials import material_notes  # noqa: E402
from freecad.PartReview.domain.mesh_texts import material_note_text  # noqa: E402
from freecad.PartReview.domain.models import UnitSystem  # noqa: E402

OUT = open(os.environ.get("PARTREVIEW_OUT", os.path.join(tempfile.gettempdir(),
                                                         "material_notes.txt")), "w")
failures = []


def check(name, condition, detail=""):
    OUT.write("%s %s %s\n" % ("PASS" if condition else "FAIL", name, detail))
    OUT.flush()
    if not condition:
        failures.append(name)


def material(doc, analysis, name, young, nu, refs=None):
    obj = ObjectsFem.makeMaterialSolid(doc, name)
    m = obj.Material
    m.update({"Name": name, "YoungsModulus": young, "PoissonRatio": nu})
    obj.Material = m
    if refs is not None:
        obj.References = refs
    analysis.addObject(obj)
    return obj


doc = App.newDocument("MaterialNotes")
a = doc.addObject("Part::Feature", "A")
a.Shape = Part.makeBox(10, 10, 10)
b = doc.addObject("Part::Feature", "B")
b.Shape = Part.makeBox(10, 10, 10, App.Vector(20, 0, 0))
lonely = doc.addObject("Part::Feature", "Lonely")
lonely.Shape = Part.makeBox(5, 5, 5, App.Vector(40, 0, 0))
analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
for part in (a, b):
    fixed = ObjectsFem.makeConstraintFixed(doc, "Fix" + part.Name)
    fixed.References = [(part, "Face1")]
    analysis.addObject(fixed)
material(doc, analysis, "PLA", "3600 MPa", "0.36", [(a, "Solid1")])
material(doc, analysis, "TPU", "26 MPa", "0.48", [(b, "Solid1")])
doc.recompute()

unit = UnitSystem.FREECAD_SCHEMA
names = lambda part: [m.name for m in materials_of_part(doc, part, unit)]  # noqa: E731
check("material referenced to A is read for A only", names(a) == ["PLA"], str(names(a)))
check("material referenced to B is read for B only", names(b) == ["TPU"], str(names(b)))
check("part outside every analysis: no material", names(lonely) == [], str(names(lonely)))

notes_a = [n.kind for n in material_notes(materials_of_part(doc, a, unit))]
notes_b = [n.kind for n in material_notes(materials_of_part(doc, b, unit))]
check("PLA: maybe printed", notes_a == ["maybe_printed"], str(notes_a))
check("TPU (E 26 MPa): nearly incompressible only", notes_b == ["incompressible"], str(notes_b))

whole = ObjectsFem.makeAnalysis(doc, "Analysis2")
fix = ObjectsFem.makeConstraintFixed(doc, "FixLonely")
fix.References = [(lonely, "Face1")]
whole.addObject(fix)
material(doc, whole, "Steel", "210 GPa", "0.3")  # no References: whole analysis
doc.recompute()
check("material without References applies to the analysis", names(lonely) == ["Steel"],
      str(names(lonely)))

tr = Translator("pt_BR")
for note in material_notes(materials_of_part(doc, a, unit)):
    text = material_note_text(note, tr)
    OUT.write("  text: %s\n" % text)
    check("text has the material and E", "PLA" in text and "3" in text and "{" not in text)
App.closeDocument(doc.Name)

OUT.write("ALL PASS\n" if not failures else "FAILED: %d\n" % len(failures))
OUT.close()
