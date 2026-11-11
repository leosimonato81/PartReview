# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
#
# A1 - validation where parts are decided: a stress concentration with a known
# answer. Plate with a central circular hole, uniaxial tension (plane stress).
#
# Reference (net-section convention):
#   W = 40 mm wide, L = 160 mm long, t = 2.5 mm thick, hole d = 10 mm (d/W = 0.25);
#   F = 750 N along the length.
#   sigma_net   = F / ((W - d) t) = 10.00 MPa   (sigma_gross = F / (W t) = 7.50 MPa)
#   Kt_net      = 2 + (1 - d/W)^3 = 2.4219      (Heywood's formula for the
#                 finite-width plate, as given in Peterson's Stress Concentration Factors)
#   sigma_max   = Kt_net * sigma_net = 24.22 MPa
#   = the hoop stress sigma_xx at the two hole-edge points on the transverse axis
#   (theta = 90 deg from the load axis), where the stress state is uniaxial.
#   An earlier header of this script said 27.29 MPa: that is 2 + (1 - 0.1)^3 =
#   2.729 times 10 MPa, i.e. Heywood for d/W = 0.1, not for this plate.
#   The plane-stress value is a 2D answer; through the thickness the 3D hole-edge
#   stress varies (mid-plane above, faces below), so both are reported.
#
# What is compared: sigma_xx at the hole wall (nodal values written by CalculiX),
# the same quantity as the reference. The largest von Mises on the wall is
# reported too (what the report shows), but it is not the reference quantity.
# Checks of the model itself: mean sigma_xx in the far field (x = 3L/4) must be
# sigma_gross; a longer plate (2L) shows whether the clamped end disturbs the hole.
#
# Studies (PARTREVIEW_A1_STUDIES chooses, default all: "1,1b,2,3"):
#   1. Convergence refined by CURVATURE (global h = 2 mm; Gmsh elements per
#      2*pi on the hole: 12 -> 24 -> 48 -> 96, i.e. hole size pi*d/N = 2.6 ->
#      0.33 mm); each mesh twice, since Gmsh did not give the same mesh twice;
#      Richardson extrapolation on the means when the sequence is monotonic.
#   1b. Same with a mesh REGION on the hole wall (1 -> 0.125 mm): kept because
#      its 0.5 mm mesh had an element CalculiX rejected (nonpositive jacobian).
#   2. The mesh options the assistant offers for this part (its own rules, unchanged).
#   3. Sensitivity to the plate length (clamp effect).
#   4. Systematic convergence on a 1/8 model (symmetry about x, y and z: both
#      ends pulled, the textbook problem): UNIFORM mesh over the whole model
#      (min = max size, no curvature sizing, curved 2nd-order edges), sizes
#      2.0 -> 1.59 -> 1.26 -> 1.0 -> 0.79 -> 0.63 mm (ratio 2^(1/3)), Richardson
#      with that ratio on the last three; the plane-stress reference is compared
#      with sigma_xx AVERAGED THROUGH THE THICKNESS along the hole-edge line
#      (x = 0 on the symmetry plane), mid-plane and face bracket it;
#      plus the model length (40 vs 80 mm from the hole centre) at 1.0 mm.
#      Studies 1/1b refine only along the hole, which is not a systematic
#      refinement: their peaks oscillated by +-2.5 % (2026-11-10).
# PARTREVIEW_A1_EDGES=curved uses curved 2nd-order elements in studies 1, 1b, 3
# (default "straight", the assistant's setting): with straight edges the hole is
# a polygon, whose corners may disturb the peak.
# Before CalculiX every mesh is checked for inverted or flat elements (corner
# volume, domain/quality.py); such a mesh is reported and not solved.
#
# Safety (CLAUDE.md: never freeze the computer). An earlier version called Gmsh
# inside FreeCAD without limits and froze the owner's PC (1.5 M nodes). Now:
# - refuses to start with less than MIN_FREE_MB of available memory;
# - Gmsh runs as a watched process (time and memory limits) and its mesh is
#   loaded into FreeCAD only below NODE_BUDGET nodes;
# - CalculiX runs as a watched process (time limit, half of the free memory),
#   with 1 thread so repeated runs give identical numbers.
#
# Run (FreeCAD 1.1.4 Flatpak; always with a COPY of user.cfg):
#   T=~/.var/app/org.freecad.FreeCAD/data/partreview_tmp
#   cp $T/test_user.cfg $T/test_user_a1.cfg
#   flatpak run --command=freecadcmd --filesystem=<repo> --filesystem=$T \
#     --env=PARTREVIEW_REPO=<repo> --env=PARTREVIEW_OUT=$T/a1.txt \
#     org.freecad.FreeCAD --user-cfg $T/test_user_a1.cfg \
#     -c "exec(open('<repo>/tests/freecad/validate_plate_hole.py').read())"
# The Flatpak has its own /tmp: PARTREVIEW_OUT must point to a folder it can see.

import dataclasses
import math
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
from freecad.PartReview.adapters.error_estimator import estimate  # noqa: E402
from freecad.PartReview.adapters.machine import machine_profile  # noqa: E402
from freecad.PartReview.domain.mesh_sizing import mesh_options  # noqa: E402
from freecad.PartReview.domain.models import Vec3  # noqa: E402
from freecad.PartReview.domain.quality import mesh_quality  # noqa: E402

W, L, T, D, F = 40.0, 160.0, 2.5, 10.0, 750.0
E_MPA, NU = 210000.0, 0.30
SIGMA_NET = F / ((W - D) * T)
SIGMA_GROSS = F / (W * T)
KT_NET = 2.0 + (1.0 - D / W) ** 3
EXACT = KT_NET * SIGMA_NET

GLOBAL_SIZE = 2.0  # mm, below t (a size above t gave inverted elements)
HOLE_SIZES = (1.0, 0.5, 0.25, 0.125)  # mm, mesh region on the hole wall (study 1b)
CURVATURES = (12, 24, 48, 96)  # Gmsh elements per 2*pi radians (study 1)
REPEATS = 2
STUDIES = set(os.environ.get("PARTREVIEW_A1_STUDIES", "1,1b,2,3,4").split(","))
EIGHTH_HALF = 40.0  # mm from the hole centre to the loaded end (1/8 model)
UNIFORM_RATIO = 2.0 ** (1.0 / 3.0)  # each size 1.26 x smaller: twice the elements
UNIFORM_SIZES = tuple(round(2.0 / UNIFORM_RATIO ** k, 3) for k in range(6))  # 2.0 -> 0.63 mm
# "straight" (the assistant's default, SecondOrderLinear) or "curved" 2nd-order edges,
# for studies 1, 1b and 3; study 2 keeps the assistant's own options.
EDGES = os.environ.get("PARTREVIEW_A1_EDGES", "straight")
NODE_BUDGET = 60000  # CalculiX on a thin part: ~1 GB at 54 000 nodes (CLAUDE.md)
MIN_FREE_MB = 3000
GMSH_TIME_S, GMSH_MEMORY_MB = 120, 1000
CCX_TIME_S = 300

optimizer.ccx_threads = lambda: 1  # deterministic results (CLAUDE.md, Testes)

OUT = open(os.environ.get("PARTREVIEW_OUT", os.path.join(tempfile.gettempdir(),
                                                         "plate_hole.txt")), "w")


def say(*parts):
    OUT.write(" ".join(str(p) for p in parts) + "\n")
    OUT.flush()


def build(length):
    doc = App.newDocument("PlateHole")
    plate = Part.makeBox(length, W, T)
    hole = Part.makeCylinder(D / 2, T, App.Vector(length / 2, W / 2, 0))
    part = doc.addObject("Part::Feature", "Plate")
    part.Shape = plate.cut(hole)
    doc.recompute()
    faces = part.Shape.Faces
    clamp = next(i for i, f in enumerate(faces, 1) if abs(f.CenterOfMass.x) < 1e-6)
    pull = next(i for i, f in enumerate(faces, 1) if abs(f.CenterOfMass.x - length) < 1e-6)
    wall = next(i for i, f in enumerate(faces, 1) if f.Surface.TypeId == "Part::GeomCylinder")
    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
    analysis.addObject(ObjectsFem.makeSolverCalculiXCcxTools(doc, "Solver"))
    mat = ObjectsFem.makeMaterialSolid(doc, "Steel")
    m = mat.Material
    m.update({"Name": "Steel", "YoungsModulus": "%g MPa" % E_MPA, "PoissonRatio": str(NU),
              "Density": "7900 kg/m^3"})
    mat.Material = m
    analysis.addObject(mat)
    fixed = ObjectsFem.makeConstraintFixed(doc, "Clamp")
    fixed.References = [(part, "Face%d" % clamp)]
    analysis.addObject(fixed)
    force = ObjectsFem.makeConstraintForce(doc, "Pull")
    force.References = [(part, "Face%d" % pull)]
    force.Force = "%g N" % F
    force.Direction = (part, ["Face%d" % pull])  # normal of the end face: along the length
    force.Reversed = False
    analysis.addObject(force)
    doc.recompute()
    return doc, part, analysis, "Face%d" % wall


def build_eighth(half_length):
    """1/8 of the plate: x >= 0, y >= 0, z >= 0 with the hole centre at the origin;
    symmetry planes x = 0, y = 0, z = 0 hold only the normal displacement; the
    end x = half_length carries F/4 (its area is a quarter of the full end)."""
    doc = App.newDocument("PlateHoleEighth")
    block = Part.makeBox(half_length, W / 2, T / 2)
    hole = Part.makeCylinder(D / 2, T / 2, App.Vector(0, 0, 0))
    part = doc.addObject("Part::Feature", "Plate")
    part.Shape = block.cut(hole)
    doc.recompute()
    faces = list(enumerate(part.Shape.Faces, 1))

    def plane(axis, value):
        return next(i for i, f in faces if f.Surface.TypeId == "Part::GeomPlane"
                    and abs(getattr(f.CenterOfMass, axis) - value) < 1e-6
                    and abs(getattr(f.normalAt(0, 0), axis)) > 0.99)

    wall = next(i for i, f in faces if f.Surface.TypeId == "Part::GeomCylinder")
    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
    analysis.addObject(ObjectsFem.makeSolverCalculiXCcxTools(doc, "Solver"))
    mat = ObjectsFem.makeMaterialSolid(doc, "Steel")
    m = mat.Material
    m.update({"Name": "Steel", "YoungsModulus": "%g MPa" % E_MPA, "PoissonRatio": str(NU),
              "Density": "7900 kg/m^3"})
    mat.Material = m
    analysis.addObject(mat)
    for axis in "xyz":
        sym = ObjectsFem.makeConstraintDisplacement(doc, "Sym" + axis.upper())
        sym.References = [(part, "Face%d" % plane(axis, 0.0))]
        setattr(sym, axis + "Free", False)
        setattr(sym, axis + "Displacement", 0.0)
        analysis.addObject(sym)
    pull = plane("x", half_length)
    force = ObjectsFem.makeConstraintForce(doc, "Pull")
    force.References = [(part, "Face%d" % pull)]
    force.Force = "%g N" % (F / 4)
    force.Direction = (part, ["Face%d" % pull])
    force.Reversed = False
    analysis.addObject(force)
    doc.recompute()
    return doc, part, analysis, "Face%d" % wall


def make_mesh(doc, part, analysis, option, refine):
    """Assistant mesh object with ``option``, meshed by a watched Gmsh; loaded into
    FreeCAD only below the node budget. Returns (nodes, problem)."""
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
    job.tools.update_properties()  # load the mesh written by Gmsh
    doc.recompute()
    positions = {n: Vec3(v.x, v.y, v.z) for n, v in mesh.FemMesh.Nodes.items()}
    quality = mesh_quality(fem_reader.read_volume_elements(mesh), positions)
    if quality.invalid_elements:
        return mesh.FemMesh.NodeCount, ("%d inverted/flat elements (rho_min %.3g)"
                                        % (quality.invalid_elements, quality.ratio_min))
    return mesh.FemMesh.NodeCount, ""


def solve(analysis):
    """CalculiX through the optimizer's watched job (memory and time limits)."""
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


def full_frame(length):
    """Where to measure on the full plate: hole centre (x, y), mid-plane z, face
    z values, far-field x."""
    return (length / 2, W / 2, T / 2, (0.0, T), 0.75 * length)


def eighth_frame(half_length):
    """Same on the 1/8 model: hole centre at the origin, z = 0 is the plate's
    mid-plane (symmetry) and z = t/2 its face."""
    return (0.0, 0.0, 0.0, (T / 2,), 0.75 * half_length)


def measure(result, part, wall, frame, hole_size):
    """Reference quantities from one result (all stresses in MPa)."""
    fem = result.Mesh.FemMesh
    index = {n: i for i, n in enumerate(result.NodeNumbers)}
    sxx, vm = result.NodeStressXX, result.vonMises
    if not sxx:
        raise RuntimeError("the result has no NodeStressXX")
    pos = fem.Nodes
    cx, cy, z_mid, z_faces, x_far = frame
    # Hole-wall nodes chosen geometrically (radius d/2), not by
    # FemMesh.getNodesByFace: on a 0.5 mm region mesh that call returned 487 of
    # the 824 wall nodes (A1b, 2026-11-11) and the peak looked like 12 MPa at 60 deg.
    nodes = {n for n, p in pos.items()
             if abs(math.hypot(p.x - cx, p.y - cy) - D / 2) < 1e-3 and n in index}

    def angle(n):  # degrees from the load axis (x), 0..180
        p = pos[n]
        return abs(math.degrees(math.atan2(p.y - cy, p.x - cx)))

    peak = max(nodes, key=lambda n: sxx[index[n]])
    # Hole-edge line (theta ~ 90 deg): wall nodes within half an element of the
    # transverse axis, split by height to see the variation through the thickness.
    tol = max(0.5, math.degrees(0.5 * hole_size / (D / 2)))
    edge = [n for n in nodes if abs(angle(n) - 90.0) <= tol]
    faces = [sxx[index[n]] for n in edge if any(abs(pos[n].z - z) < 1e-6 for z in z_faces)]
    mid = min(edge, key=lambda n: abs(pos[n].z - z_mid)) if edge else None
    # Through-thickness mean along the exact hole-edge line (nodes on the line
    # theta = 90 deg; it exists on the 1/8 model, where it lies in the symmetry
    # plane x = 0): trapezoidal rule over z, divided by the height covered.
    line = sorted((pos[n].z, sxx[index[n]]) for n in nodes if abs(pos[n].x - cx) < 1e-6)
    if len(line) >= 2 and line[-1][0] > line[0][0]:
        area = sum(0.5 * (a[1] + b[1]) * (b[0] - a[0]) for a, b in zip(line, line[1:]))
        edge_avg = area / (line[-1][0] - line[0][0])
    else:
        edge_avg = float("nan")
    # Far field: nodes in a slice at x_far (between hole and loaded end).
    far = [sxx[index[n]] for n, p in pos.items()
           if abs(p.x - x_far) < 0.5 * GLOBAL_SIZE and n in index]
    positions = {n: (v.x, v.y, v.z) for n, v in pos.items()}
    zz = estimate(positions, fem_reader.read_volume_elements(result.Mesh),
                  fem_reader.read_displacement_vectors(result), E_MPA, NU)
    local = dict(zip(zz.node_ids.tolist(), zz.node_indicator.tolist()))
    return {
        "sxx_max": sxx[index[peak]], "angle": angle(peak),
        "edge_mid": sxx[index[mid]] if mid is not None else float("nan"),
        "edge_faces": (sum(faces) / len(faces)) if faces else float("nan"),
        "edge_avg": edge_avg, "edge_line_nodes": len(line),
        "vm_max": max(vm[index[n]] for n in nodes),
        "far_mean": (sum(far) / len(far)) if far else float("nan"),
        "zz_local": 100.0 * local.get(peak, float("nan")),
        "zz_global": 100.0 * zz.relative_error,
    }


HEADER = ("%-12s %6s %6s %7s %7s %8s %8s %7s %7s %8s %7s %7s %6s %7s %7s %6s %5s"
          % ("case", "h_glob", "h_hole", "nodes", "sxx_max", "diff", "edge_mid", "edge_fc",
             "edge_avg", "avg_diff", "vm_max", "far", "angle", "ZZ loc", "ZZ glob", "ccxMB",
             "s"))


def run_case(case, doc, part, analysis, wall, option, refine, hole_size, frame):
    started = time.time()
    nodes, problem = make_mesh(doc, part, analysis, option, refine)
    if problem:
        say("%-12s %6.3g %6.3g %7d  NOT SOLVED: %s" % (case, option.max_size, hole_size,
                                                       nodes, problem))
        return None
    try:
        result, ccx_mb = solve(analysis)
    except RuntimeError as err:
        say("%-12s %6.3g %6.3g %7d  FAILED: %s" % (case, option.max_size, hole_size, nodes,
                                                   str(err).replace("\n", " ")[:160]))
        return None
    m = measure(result, part, wall, frame, hole_size)
    if math.isnan(m["edge_mid"]) or abs(m["angle"] - 90.0) > 10.0:
        # No hole-edge nodes at 90 deg, or the peak far from them: the mesh of the
        # hole wall is not what was asked for (seen with a 0.5 mm region). The
        # numbers are not used; the case is reported as suspect.
        say("%-12s %6.3g %6.3g %7d  SUSPECT: no hole-edge nodes at 90 deg or peak at %.0f deg "
            "(sxx_max %.2f, far %.3f); not used" % (case, option.max_size, hole_size, nodes,
                                                    m["angle"], m["sxx_max"], m["far_mean"]))
        return None
    say("%-12s %6.3g %6.3g %7d %7.2f %7.2f%% %8.2f %7.2f %8.3f %7.2f%% %7.2f %7.3f %6.1f "
        "%6.2f%% %6.2f%% %6.0f %5.0f"
        % (case, option.max_size, hole_size, nodes, m["sxx_max"],
           100.0 * (m["sxx_max"] - EXACT) / EXACT, m["edge_mid"], m["edge_faces"],
           m["edge_avg"], 100.0 * (m["edge_avg"] - EXACT) / EXACT,
           m["vm_max"], m["far_mean"], m["angle"], m["zz_local"], m["zz_global"],
           ccx_mb, time.time() - started))
    return m


def richardson(values, ratio=2.0):
    """(observed order p, extrapolated value) from the last three of a sequence
    refined by a constant ratio; None when it does not converge monotonically."""
    if len(values) < 3:
        return None
    f1, f2, f3 = values[-3:]
    d1, d2 = f2 - f1, f3 - f2
    if d1 == 0 or d2 == 0 or (d1 > 0) != (d2 > 0) or abs(d2) >= abs(d1):
        return None
    p = math.log(d1 / d2) / math.log(ratio)
    return p, f3 + d2 / (ratio ** p - 1.0)


def main():
    free = machine_profile().available_mb
    if free < MIN_FREE_MB:
        say("NOT RUN: only %.0f MB available (needs %d MB)" % (free, MIN_FREE_MB))
        return
    say("A1 plate with a hole: %gx%gx%g mm, d = %g mm, F = %g N, E = %g MPa, nu = %g"
        % (L, W, T, D, F, E_MPA, NU))
    say("reference: sigma_net %.2f MPa, sigma_gross %.2f MPa, Kt_net %.4f -> "
        "sigma_max %.2f MPa (sigma_xx at the hole edge, plane stress)"
        % (SIGMA_NET, SIGMA_GROSS, KT_NET, EXACT))
    say("available memory %.0f MB; node budget %d; Gmsh limit %d MB; CalculiX limit %.0f MB"
        % (free, NODE_BUDGET, GMSH_MEMORY_MB, 0.5 * free))
    say("columns: sxx_max = largest sigma_xx on the hole wall (angle from the load "
        "axis); edge_mid = sigma_xx at theta 90 deg, mid-plane node; edge_fc = mean at "
        "the two faces; far = mean sigma_xx at x = 3L/4 (expected %.2f)" % SIGMA_GROSS)
    doc, part, analysis, wall = build(L)
    summary = geometry_reader.summarize(part)
    options = mesh_options(summary)
    say("characteristic thickness %.2f mm; assistant options: %s"
        % (summary.characteristic_thickness,
           ", ".join("%s h=%g" % (o.level.value, o.max_size) for o in options)))
    base = dataclasses.replace(options[0], max_size=GLOBAL_SIZE, min_size=0.0, local_size=0.0,
                               straight_edges=(EDGES != "curved"))
    say("element edges for studies 1, 1b, 3: %s" % EDGES)

    def report_fit(label, values):
        for key in ("sxx_max", "edge_mid"):
            fit = richardson([v[key] for v in values])
            if fit:
                say("Richardson (%s) on %s: observed order %.2f, extrapolated %.2f MPa "
                    "(%+.2f%% vs %.2f)" % (label, key, fit[0], fit[1],
                                           100.0 * (fit[1] - EXACT) / EXACT, EXACT))
            else:
                say("Richardson (%s) on %s: not applicable (fewer than 3 points or not "
                    "converging monotonically)" % (label, key))

    if "1" in STUDIES:
        say("\n1. Convergence refined by curvature (no region; hole size = pi*d/N)")
        say(HEADER)
        means = []
        for n in CURVATURES:
            option = dataclasses.replace(base, curvature=n)
            runs = [run_case("curv%d #%d" % (n, k + 1), doc, part, analysis, wall, option, (),
                             math.pi * D / n, full_frame(L)) for k in range(REPEATS)]
            runs = [r for r in runs if r is not None]
            if not runs:
                break
            means.append({key: sum(r[key] for r in runs) / len(runs)
                          for key in ("sxx_max", "edge_mid")})
            spread = max(r["sxx_max"] for r in runs) - min(r["sxx_max"] for r in runs)
            say("  N=%d: mean sxx_max %.3f MPa (%+.2f%%), spread between runs %.3f MPa"
                % (n, means[-1]["sxx_max"], 100.0 * (means[-1]["sxx_max"] - EXACT) / EXACT,
                   spread))
        report_fit("curvature, means", means)

    sequence = []
    if "1b" in STUDIES:
        say("\n1b. Convergence with a mesh region on the hole wall")
        say(HEADER)
        for size in HOLE_SIZES:
            option = dataclasses.replace(base, local_size=size)
            m = run_case("region", doc, part, analysis, wall, option, (wall,), size,
                         full_frame(L))
            if m is None:
                break
            sequence.append((size, m))
        report_fit("region", [m for _, m in sequence])

    if "2" in STUDIES:
        say("\n2. Mesh options of the assistant (its own rules; h_hole = size on the hole wall)")
        say(HEADER)
        targets = mesh_runner.constraint_targets(doc, part)
        refine = tuple(s for _, _, subs in targets for s in subs if s.startswith("Face")
                       and part.Shape.getElement(s).Area <= 0.05 * summary.area)
        say("refined faces (supports/loads):", refine)
        for option in options:
            hole = next((size for size, faces in option.radius_regions if wall in faces),
                        option.max_size)  # size on the hole wall (A2.2), else the global one
            run_case(option.level.value, doc, part, analysis, wall, option, refine,
                     hole, full_frame(L))
    App.closeDocument(doc.Name)

    if "3" in STUDIES and sequence:
        size = sequence[-1][0]  # finest size that gave a valid result
        say("\n3. Plate length (clamp effect), hole size %g mm" % size)
        say(HEADER)
        for length in (L, 2 * L):
            doc, part, analysis, wall = build(length)
            option = dataclasses.replace(base, local_size=size)
            run_case("L=%g" % length, doc, part, analysis, wall, option, (wall,), size,
                     full_frame(length))
            App.closeDocument(doc.Name)

    if "4" in STUDIES:
        say("\n4. Systematic convergence, 1/8 model, uniform mesh, curved edges "
            "(end at %g mm from the hole centre)" % EIGHTH_HALF)
        say(HEADER)
        doc, part, analysis, wall = build_eighth(EIGHTH_HALF)
        values = []
        for h in UNIFORM_SIZES:
            option = dataclasses.replace(base, max_size=h, min_size=h, curvature=0,
                                         straight_edges=False, local_size=0.0)
            m = run_case("eighth", doc, part, analysis, wall, option, (), h,
                         eighth_frame(EIGHTH_HALF))
            if m is None:
                break
            values.append(m)
        App.closeDocument(doc.Name)
        for key in ("edge_avg", "edge_mid", "sxx_max"):
            fit = richardson([v[key] for v in values], ratio=UNIFORM_RATIO)
            if fit:
                say("Richardson (uniform, ratio 2^(1/3), last three) on %s: observed order %.2f, "
                    "extrapolated %.3f MPa (%+.2f%% vs %.2f)"
                    % (key, fit[0], fit[1], 100.0 * (fit[1] - EXACT) / EXACT, EXACT))
            else:
                say("Richardson (uniform) on %s: not applicable (fewer than 3 points or "
                    "not converging monotonically)" % key)
        say("model length check (end at %g and %g mm), h = 1.26 and 1.0 mm:"
            % (EIGHTH_HALF, 2 * EIGHTH_HALF))
        say(HEADER)
        for h in (1.26, 1.0):
            for half in (EIGHTH_HALF, 2 * EIGHTH_HALF):
                doc, part, analysis, wall = build_eighth(half)
                option = dataclasses.replace(base, max_size=h, min_size=h, curvature=0,
                                             straight_edges=False, local_size=0.0)
                run_case("end=%g" % half, doc, part, analysis, wall, option, (), h,
                         eighth_frame(half))
                App.closeDocument(doc.Name)


try:
    main()
except Exception:  # test script: write the traceback where the run can be read
    import traceback
    say(traceback.format_exc())
OUT.close()
