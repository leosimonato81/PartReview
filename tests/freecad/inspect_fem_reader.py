# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
#
# Integration check for adapters/fem_reader.py. Run inside FreeCAD with the
# FEM document open (Python console):
#   exec(open("<repo>/tests/freecad/inspect_fem_reader.py", encoding="utf-8").read())
# Read-only: it changes nothing in the document.

import cProfile
import io
import pstats
import sys
import time

import FreeCAD as App

# Drop every cached PartReview module so all of them are re-imported fresh and
# consistently (a partial importlib.reload leaves two copies of the enums).
for _name in [n for n in sys.modules if n.startswith("freecad.PartReview")]:
    del sys.modules[_name]

from freecad.PartReview.domain import units  # noqa: E402
from freecad.PartReview.domain.models import UnitSystem  # noqa: E402
from freecad.PartReview.adapters import fem_reader  # noqa: E402


def fmt(q):
    return units.format_quantity(q, significant=4) if q is not None else "-"


def main():
    doc = App.ActiveDocument
    if doc is None:
        App.Console.PrintError("inspect_fem_reader: open a document first.\n")
        return
    results = fem_reader.list_mechanical_results(doc)
    print("=== PartReview fem_reader check ===")
    print("mechanical results:", results)
    if not results:
        return

    name = results[0][0]
    obj = doc.getObject(name)
    analysis = fem_reader.find_analysis(obj)
    print("--- time per part ---")
    for label, call in (
        ("FemMesh property", lambda: obj.Mesh.FemMesh),
        ("FemMesh.Nodes", lambda: obj.Mesh.FemMesh.Nodes),
        ("FemMesh.Volumes", lambda: obj.Mesh.FemMesh.Volumes),
        ("FemMesh.Faces", lambda: obj.Mesh.FemMesh.Faces),
        ("FemMesh.Edges", lambda: obj.Mesh.FemMesh.Edges),
        ("read_mesh", lambda: fem_reader.read_mesh(obj.Mesh)),
        ("read_fields", lambda: fem_reader.read_fields(obj, UnitSystem.MPA_MM)),
        ("read_materials", lambda: fem_reader.read_materials(analysis, UnitSystem.MPA_MM)),
        ("read_constraints", lambda: fem_reader.read_constraints(analysis, UnitSystem.MPA_MM)),
    ):
        t0 = time.perf_counter()
        call()
        print("  %-18s %.2f s" % (label, time.perf_counter() - t0))

    profiler = cProfile.Profile()
    start = time.perf_counter()
    try:
        res = profiler.runcall(fem_reader.read_fem_result, doc, name)
    except fem_reader.FemReadError as err:
        print("EXPECTED ERROR:", err.key, err.detail)
        return
    elapsed = time.perf_counter() - start
    stream = io.StringIO()
    pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats(12)
    print("--- profile (top 12, cumulative) ---")
    print(stream.getvalue())

    m = res.mesh
    print("result   :", res.label, "| solver:", res.solver, "| type:", res.analysis_type)
    print("read time: %.2f s" % elapsed)
    print("mesh     : %d nodes, %d elements, order %d, length unit %s"
          % (m.node_count, m.element_count, m.element_order, m.length_unit))
    print("bbox     :", m.bounding_box())
    for kind, field in res.fields.items():
        hi, lo = field.maximum(m), field.minimum(m)
        print("%-12s max %s at node %d %s" % (kind.value, fmt(hi.value), hi.node_id,
                                              tuple(round(c, 2) for c in hi.position)))
        print("%-12s min %s at node %d %s" % ("", fmt(lo.value), lo.node_id,
                                              tuple(round(c, 2) for c in lo.position)))
    for mat in res.materials:
        print("material : %s | E=%s | nu=%s | rho=%s | yield=%s" % (
            mat.name, fmt(mat.youngs_modulus), mat.poisson_ratio,
            fmt(mat.density), fmt(mat.yield_strength)))
    for c in res.constraints:
        print("constraint: %-9s %-20s refs=%s magnitude=%s direction=%s" % (
            c.kind.value, c.label, c.references, fmt(c.magnitude), c.direction))

    print("--- same values with unit system FREECAD_SCHEMA ---")
    schema_fields = fem_reader.read_fields(obj, UnitSystem.FREECAD_SCHEMA)
    for kind, field in schema_fields.items():
        print("%-12s max %s" % (kind.value, fmt(field.maximum(m).value)))
    for c in fem_reader.read_constraints(analysis, UnitSystem.FREECAD_SCHEMA):
        print("constraint: %-20s magnitude=%s" % (c.label, fmt(c.magnitude)))
    print("=== END ===")


main()
