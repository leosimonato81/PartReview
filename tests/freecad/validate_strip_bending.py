# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
#
# A2.3 - bending of a thin strip: does a mesh with one or two elements through the
# thickness give the bending stress? (The A1 plate is in tension, which does not
# test that.)
#
# Cantilever strip L x W x t = 160 x 20 x 2.5 mm, clamped at x = 0, tip load
# F = 5 N downwards (-z) on the end face x = L.
# Reference (equilibrium, any linear material): at a section x, M = F (L - x),
#   sigma_xx at the top face = + M c / I, at the bottom face = - M c / I,
#   c = t/2, I = W t^3 / 12. Compared node by node on the faces z = t and z = 0,
#   in the middle third of the width (away from the free edges) and of the length
#   (away from the clamp and the load): mean ratio sigma / (M c / I).
# Check (not the criterion): tip deflection between beam theory F L^3 / (3 E I)
# and the plate value (x (1 - nu^2)), since a strip W/t = 8 is in between.
#
# Meshes: the assistant's options (its own rules, unchanged) and uniform meshes
# of 2.5 -> 1.77 -> 1.25 mm (1 to 2 elements through the thickness).
#
# Safety (CLAUDE.md): refuses to start below 3 GB free; Gmsh watched (1 GB,
# 2 min), mesh loaded only below 60 000 nodes and checked for degenerate
# elements; CalculiX watched (half of the free memory, 5 min), 1 thread.
#
#   T=~/.var/app/org.freecad.FreeCAD/data/partreview_tmp
#   cp $T/test_user.cfg $T/test_user_strip.cfg
#   flatpak run --command=freecadcmd --filesystem=<repo> --filesystem=$T \
#     --env=PARTREVIEW_REPO=<repo> --env=PARTREVIEW_OUT=$T/strip.txt \
#     org.freecad.FreeCAD --user-cfg $T/test_user_strip.cfg \
#     -c "exec(open('<repo>/tests/freecad/validate_strip_bending.py').read())"

import dataclasses
import os
import sys
import tempfile
import time

import FreeCAD as App
import ObjectsFem
import Part

REPO = os.environ.get("PARTREVIEW_REPO") or os.getcwd()
sys.path.insert(0, REPO)
for name in [n for n in sys.modules if n.startswith("freecad.PartReview")]:
    del sys.modules[name]

from freecad.PartReview.adapters import fem_reader, geometry_reader, mesh_runner  # noqa: E402
from freecad.PartReview.adapters import optimizer  # noqa: E402
from freecad.PartReview.adapters.machine import machine_profile  # noqa: E402
from freecad.PartReview.domain.mesh_sizing import mesh_options  # noqa: E402

L, W, T, F = 160.0, 20.0, 2.5, 5.0
E_MPA, NU = 210000.0, 0.30
I = W * T ** 3 / 12.0
C = T / 2.0
BEAM_TIP = F * L ** 3 / (3.0 * E_MPA * I)
PLATE_TIP = BEAM_TIP * (1.0 - NU ** 2)
UNIFORM_SIZES = (2.5, 1.77, 1.25)
NODE_BUDGET = 60000
MIN_FREE_MB = 3000
GMSH_TIME_S, GMSH_MEMORY_MB = 120, 1000
CCX_TIME_S = 300

optimizer.ccx_threads = lambda: 1  # deterministic results (CLAUDE.md, Testes)

OUT = open(os.environ.get("PARTREVIEW_OUT", os.path.join(tempfile.gettempdir(),
                                                         "strip.txt")), "w")


def say(*parts):
    OUT.write(" ".join(str(p) for p in parts) + "\n")
    OUT.flush()


def build():
    doc = App.newDocument("Strip")
    part = doc.addObject("Part::Feature", "Strip")
    part.Shape = Part.makeBox(L, W, T)
    doc.recompute()
    faces = list(enumerate(part.Shape.Faces, 1))

    def face(axis, value):
        return next(i for i, f in faces if abs(getattr(f.CenterOfMass, axis) - value) < 1e-6
                    and abs(getattr(f.normalAt(0, 0), axis)) > 0.99)

    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
    analysis.addObject(ObjectsFem.makeSolverCalculiXCcxTools(doc, "Solver"))
    mat = ObjectsFem.makeMaterialSolid(doc, "Steel")
    m = mat.Material
    m.update({"Name": "Steel", "YoungsModulus": "%g MPa" % E_MPA, "PoissonRatio": str(NU),
              "Density": "7900 kg/m^3"})
    mat.Material = m
    analysis.addObject(mat)
    fixed = ObjectsFem.makeConstraintFixed(doc, "Clamp")
    fixed.References = [(part, "Face%d" % face("x", 0.0))]
    analysis.addObject(fixed)
    force = ObjectsFem.makeConstraintForce(doc, "Tip")
    force.References = [(part, "Face%d" % face("x", L))]
    force.Force = "%g N" % F
    force.Direction = (part, ["Face%d" % face("z", T)])  # top face normal: +z ...
    force.Reversed = True  # ... reversed: downwards
    analysis.addObject(force)
    doc.recompute()
    return doc, part, analysis


def make_mesh(doc, part, analysis, option, refine):
    """Watched Gmsh; loaded (and checked) only below the node budget."""
    mesh, _ = mesh_runner.create_or_update_mesh(doc, part, option, "validation", refine)
    if mesh not in analysis.Group:
        analysis.addObject(mesh)
    doc.recompute()
    job = mesh_runner.GmshJob(mesh, GMSH_TIME_S, GMSH_MEMORY_MB, load_into_object=False)
    job.start()
    while job.poll() == job.RUNNING:
        time.sleep(0.1)
    if job.state != job.DONE:
        return job.run.nodes, "gmsh %s (peak %.0f MB)" % (job.state, job.peak_mb)
    if job.run.nodes > NODE_BUDGET:
        return job.run.nodes, "over the node budget (%d)" % NODE_BUDGET
    job._load()  # the assistant's own load: read, check degenerate elements, load
    doc.recompute()
    if job.degenerate:
        return mesh.FemMesh.NodeCount, "%d degenerate elements" % len(job.degenerate)
    return mesh.FemMesh.NodeCount, ""


def solve(analysis):
    job = optimizer.SolveJob(analysis, CCX_TIME_S, 0.5 * machine_profile().available_mb)
    job.start()
    while job.poll() == job.RUNNING:
        time.sleep(0.2)
    if job.state != job.DONE:
        raise RuntimeError("%s (%s); %s" % (job.state, job.reason, job.log_tail(3)))
    result = optimizer.latest_result(analysis)
    if result is None or result.Mesh is None:
        raise RuntimeError("no results")
    return result, job.peak_mb


def measure(result):
    pos = result.Mesh.FemMesh.Nodes
    index = {n: i for i, n in enumerate(result.NodeNumbers)}
    sxx = result.NodeStressXX
    if not sxx:
        raise RuntimeError("the result has no NodeStressXX")
    disp = fem_reader.read_displacement_vectors(result)

    def ratios(z, sign):
        out = []
        for n, p in pos.items():
            if n in index and abs(p.z - z) < 1e-6 and L / 3 <= p.x <= 2 * L / 3 \
                    and W / 3 <= p.y <= 2 * W / 3:
                ref = sign * F * (L - p.x) * C / I
                out.append(sxx[index[n]] / ref)
        return out

    top, bottom = ratios(T, 1.0), ratios(0.0, -1.0)
    tip = [disp[n][2] for n, p in pos.items() if abs(p.x - L) < 1e-6 and n in disp]
    mean = lambda v: sum(v) / len(v) if v else float("nan")  # noqa: E731
    return {"top": mean(top), "bottom": mean(bottom), "n": len(top) + len(bottom),
            "spread": (max(top + bottom) - min(top + bottom)) if top + bottom else float("nan"),
            "tip": -mean(tip)}


HEADER = "%-12s %6s %7s %9s %9s %8s %5s %9s %9s %6s %5s" % (
    "case", "h", "nodes", "top/ref", "bot/ref", "spread", "n", "tip mm", "tip/beam", "ccxMB", "s")


def run_case(case, doc, part, analysis, option, refine):
    started = time.time()
    nodes, problem = make_mesh(doc, part, analysis, option, refine)
    if problem:
        say("%-12s %6.3g %7d  NOT SOLVED: %s" % (case, option.max_size, nodes, problem))
        return None
    try:
        result, mb = solve(analysis)
    except RuntimeError as err:
        say("%-12s %6.3g %7d  FAILED: %s" % (case, option.max_size, nodes,
                                             str(err).replace("\n", " ")[:160]))
        return None
    m = measure(result)
    say("%-12s %6.3g %7d %9.4f %9.4f %8.4f %5d %9.4f %9.4f %6.0f %5.0f"
        % (case, option.max_size, nodes, m["top"], m["bottom"], m["spread"], m["n"], m["tip"],
           m["tip"] / BEAM_TIP, mb, time.time() - started))
    return m


def main():
    free = machine_profile().available_mb
    if free < MIN_FREE_MB:
        say("NOT RUN: only %.0f MB available (needs %d MB)" % (free, MIN_FREE_MB))
        return
    say("strip %gx%gx%g mm, F = %g N, E = %g MPa, nu = %g" % (L, W, T, F, E_MPA, NU))
    say("reference: sigma_xx = +-F (L - x) c / I (top/bottom); ratio 1.000 = exact. Tip "
        "deflection: beam %.4f mm, plate %.4f mm (tip/beam %.3f)"
        % (BEAM_TIP, PLATE_TIP, 1 - NU ** 2))
    say("available memory %.0f MB; node budget %d" % (free, NODE_BUDGET))
    doc, part, analysis = build()
    summary = geometry_reader.summarize(part)
    options = mesh_options(summary)
    targets = mesh_runner.constraint_targets(doc, part)
    refine = tuple(s for _, _, subs in targets for s in subs if s.startswith("Face")
                   and part.Shape.getElement(s).Area <= 0.05 * summary.area)
    say("characteristic thickness %.2f mm; refined faces (supports/loads): %s"
        % (summary.characteristic_thickness, refine))

    say("\n1. Mesh options of the assistant")
    say(HEADER)
    for option in options:
        run_case(option.level.value, doc, part, analysis, option, refine)

    say("\n2. Uniform meshes (min = max size, no refinement)")
    say(HEADER)
    for h in UNIFORM_SIZES:
        option = dataclasses.replace(options[0], max_size=h, min_size=h, local_size=0.0,
                                     radius_regions=())
        run_case("uniform", doc, part, analysis, option, ())
    App.closeDocument(doc.Name)


try:
    main()
except Exception:  # test script: write the traceback where the run can be read
    import traceback
    say(traceback.format_exc())
OUT.close()
