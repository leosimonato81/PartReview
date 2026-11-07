# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
#
# Build the example and test models in examples/ from FreeCAD's own native
# example femexamples.ccx_cantilever_faceload (steel cantilever, 8000 mm,
# 1000 x 1000 mm section, 9 MN at the tip). Reproducible: run again to rebuild.
#
#   flatpak run --command=freecadcmd --filesystem="<repo>" org.freecad.FreeCAD \
#       -c "exec(open('<repo>/tools/build_examples.py').read())"
#   (or: freecadcmd -c "exec(open('<repo>/tools/build_examples.py').read())")
#
# Environment: PARTREVIEW_REPO = repository folder (default: current folder).

import os
import tempfile

import FreeCAD as App
import ObjectsFem

# Run from the repository folder, or set PARTREVIEW_REPO.
REPO = os.environ.get("PARTREVIEW_REPO") or os.getcwd()
OUT = os.path.join(REPO, "examples")
MESH_SIZE = "250 mm"  # about 5000 nodes with 10-node tetrahedra: small files, fast reports


def mesh_and_solve(doc, analysis, mesh_obj, solve=True):
    from femmesh import gmshtools
    from femtools import ccxtools
    mesh_obj.CharacteristicLengthMax = MESH_SIZE
    mesh_obj.ElementOrder = "2nd"
    gmshtools.GmshTools(mesh_obj).create_mesh()
    doc.recompute()
    if not solve:
        return
    solver = [o for o in analysis.Group if o.TypeId.startswith("Fem::FemSolverObject")][0]
    fea = ccxtools.FemToolsCcx(analysis=analysis, solver=solver)
    fea.update_objects()
    fea.setup_working_dir(tempfile.mkdtemp(prefix="partreview_ex_"))
    fea.setup_ccx()
    fea.purge_results()
    fea.write_inp_file()
    fea.ccx_run()
    fea.load_results()


def cantilever():
    from femexamples import ccx_cantilever_faceload as ex
    doc = ex.setup()
    return doc, doc.getObject("Analysis"), doc.getObject("Mesh")


def save(doc, name):
    path = os.path.join(OUT, name)
    doc.saveAs(path)
    App.closeDocument(doc.Name)
    print("saved", path)


def build():
    os.makedirs(OUT, exist_ok=True)

    # 1. Public example: solved cantilever.
    doc, analysis, mesh = cantilever()
    mesh_and_solve(doc, analysis, mesh)
    save(doc, "viga_em_balanco.FCStd")

    # 2. Same part inside an App::Part moved and rotated (Placement test).
    doc, analysis, mesh = cantilever()
    part = doc.addObject("App::Part", "Montagem")
    part.addObject(doc.getObject("Box"))
    part.Placement = App.Placement(App.Vector(2000, 1000, 500), App.Rotation(App.Vector(0, 0, 1), 30))
    doc.recompute()
    mesh_and_solve(doc, analysis, mesh)
    save(doc, "teste_app_part.FCStd")

    # 3. Two analyses in one document: the second with half the load.
    doc, analysis, mesh = cantilever()
    mesh_and_solve(doc, analysis, mesh)
    box = doc.getObject("Box")
    second = ObjectsFem.makeAnalysis(doc, "Analysis_meia_carga")
    second.addObject(ObjectsFem.makeSolverCalculiXCcxTools(doc, "SolverMeiaCarga"))
    material = ObjectsFem.makeMaterialSolid(doc, "MaterialMeiaCarga")
    material.Material = doc.getObject("FemMaterial").Material
    second.addObject(material)
    fixed = ObjectsFem.makeConstraintFixed(doc, "FixoMeiaCarga")
    fixed.References = [(box, "Face1")]
    second.addObject(fixed)
    force = ObjectsFem.makeConstraintForce(doc, "ForcaMeiaCarga")
    force.References = [(box, "Face2")]
    force.Force = "4500000.0 N"
    force.Direction = (box, ["Edge5"])
    force.Reversed = True
    second.addObject(force)
    mesh2 = second.addObject(ObjectsFem.makeMeshGmsh(doc, "MeshMeiaCarga"))[0]
    mesh2.Shape = box
    mesh_and_solve(doc, second, mesh2)
    save(doc, "teste_duas_analises.FCStd")

    # 4. Analysis set up but never solved: the tool must say so clearly.
    doc, analysis, mesh = cantilever()
    mesh_and_solve(doc, analysis, mesh, solve=False)
    save(doc, "teste_sem_resultado.FCStd")


build()
