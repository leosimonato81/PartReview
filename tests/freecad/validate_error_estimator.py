# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
#
# Validation of adapters/error_estimator.py against theory (decision 005).
#
# Builds FreeCAD's native example femexamples.ccx_cantilever_faceload
# (steel cantilever L = 8000 mm, 1000 x 1000 mm section, F = 9 MN at the tip),
# meshes it with Gmsh at several sizes and element orders, solves with
# CalculiX, and compares the Zienkiewicz-Zhu estimate with the true error in
# the energy norm, which is known here because the exact strain energy is
# U = F * delta / 2 with delta from Timoshenko beam theory.
#
# Run (no GUI needed):
#   flatpak run --command=freecadcmd org.freecad.FreeCAD -c \
#     "exec(open('<repo>/tests/freecad/validate_error_estimator.py').read())"
# Environment: PARTREVIEW_REPO (repo path), PARTREVIEW_LOG (output file).

import math
import os
import sys
import tempfile
import traceback

import FreeCAD as App

REPO = os.environ.get("PARTREVIEW_REPO") or os.getcwd()  # run from the repository folder
sys.path.insert(0, REPO)
for _name in [n for n in sys.modules if n.startswith("freecad.PartReview")]:
    del sys.modules[_name]

from freecad.PartReview.adapters.error_estimator import estimate  # noqa: E402

F, L, B, H, E, NU = 9e6, 8000.0, 1000.0, 1000.0, 210000.0, 0.30
I_ = B * H ** 3 / 12.0
G_ = E / (2 * (1 + NU))
DELTA = F * L ** 3 / (3 * E * I_) + F * L / (5.0 / 6.0 * G_ * B * H)  # Timoshenko
ENERGY_NORM_SQ_EXACT = F * DELTA  # ||u||^2 = 2U = F * delta


def solve(h, order):
    from femexamples import ccx_cantilever_faceload as ex
    from femmesh import gmshtools
    from femtools import ccxtools
    doc = ex.setup()
    mesh = doc.getObject("Mesh")
    mesh.CharacteristicLengthMax = "%g mm" % h
    mesh.ElementOrder = order
    gmshtools.GmshTools(mesh).create_mesh()
    doc.recompute()
    solver = [o for o in doc.Objects if o.TypeId.startswith("Fem::FemSolverObject")][0]
    fea = ccxtools.FemToolsCcx(analysis=doc.Analysis, solver=solver)
    fea.update_objects()
    fea.setup_working_dir(tempfile.mkdtemp(prefix="pr_zz_"))
    fea.setup_ccx()
    fea.purge_results()
    fea.write_inp_file()
    fea.ccx_run()
    fea.load_results()
    res = [o for o in doc.Objects if getattr(o, "ResultType", "") == "Fem::ResultMechanical"][0]
    return doc, res


def main(out):
    out("Theory: tip deflection %.3f mm, ||u||^2 = F*delta = %.6e N.mm" % (DELTA, ENERGY_NORM_SQ_EXACT))
    out("%-5s %6s %7s %9s %10s %10s %7s %8s %8s" % (
        "order", "h(mm)", "nodes", "elements", "eta_ZZ(%)", "eta_true(%)", "theta",
        "vM diff", "invalid"))
    for order, sizes in (("1st", (1000, 500, 250, 166)), ("2nd", (1000, 500, 250))):
        for h in sizes:
            doc, res = solve(h, order)
            fm = res.Mesh.FemMesh
            positions = {n: (v.x, v.y, v.z) for n, v in fm.Nodes.items()}
            disp = {n: (v.x, v.y, v.z) for n, v in zip(res.NodeNumbers, res.DisplacementVectors)}
            elements = [fm.getElementNodes(e) for e in fm.Volumes]
            zz = estimate(positions, elements, disp, E, NU)
            true_sq = max(ENERGY_NORM_SQ_EXACT - zz.energy_norm_sq, 0.0)
            eta_true = math.sqrt(true_sq / ENERGY_NORM_SQ_EXACT)
            ccx_vm = dict(zip(res.NodeNumbers, res.vonMises))
            ours = dict(zip(zz.node_ids.tolist(), zz.node_von_mises.tolist()))
            vmax = max(ccx_vm.values())
            diff = max(abs(ours[n] - ccx_vm[n]) for n in ccx_vm) / vmax
            out("%-5s %6d %7d %9d %10.2f %10.2f %7.2f %7.1f%% %8d" % (
                order, h, fm.NodeCount, len(elements), 100 * zz.relative_error, 100 * eta_true,
                zz.relative_error / eta_true if eta_true > 0 else float("nan"), 100 * diff,
                zz.invalid_elements))
            App.closeDocument(doc.Name)


log_path = os.environ.get("PARTREVIEW_LOG")
_fh = open(log_path, "w", encoding="utf-8") if log_path else None


def _out(line):
    print(line)
    if _fh:
        _fh.write(line + "\n")
        _fh.flush()


try:
    main(_out)
except Exception:
    _out(traceback.format_exc())
