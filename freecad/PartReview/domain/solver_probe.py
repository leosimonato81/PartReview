# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""CalculiX trial on the user's own part (pure text processing, no Qt).

Memory and time of the direct solver depend on the mesh connectivity, which
depends on the part's shape: a compact block needed 2.6 GB at 54 000 nodes, the
owner's thin-walled part 1.0 GB at 56 000 (spike 8.0 and benchmark, same PC).
So the solver is measured on the part itself, on its smaller trial meshes, with a
generic support and load (they do not change the matrix size or sparsity):
clamped slab at one end of the longest side, total force at the other end.
"""

import re

SLAB = 0.03  # 3 % of the length at each end
TOTAL_FORCE_N = -1000.0
PROBE_ELSET = "PROBE_SOLID"


def probe_geo(geo_text: str, mesh_file: str) -> str:
    """FreeCAD's Gmsh .geo turned into one that saves only the volume as CalculiX .inp.

    Same mesh settings; surface/line groups dropped (CalculiX would need sections
    for them); the solid's physical group renamed to a known element set.
    """
    lines = []
    for line in geo_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("Physical Line", "Physical Surface", "Physical Point")):
            continue
        if stripped.startswith("Physical Volume"):
            line = re.sub(r'Physical Volume\("[^"]*"\)', 'Physical Volume("%s")' % PROBE_ELSET,
                          line)
        elif stripped.startswith("Mesh.SaveAll"):
            line = "Mesh.SaveAll = 0;"
        elif stripped.startswith("Mesh.SaveGroupsOfNodes"):
            line = "Mesh.SaveGroupsOfNodes = 0;"
        elif stripped.startswith("Save "):
            line = 'Save "%s";' % mesh_file
        lines.append(line)
    return "\n".join(lines) + "\n"


def parse_nodes(inp_text: str) -> dict:
    """{node id: (x, y, z)} from the *NODE block of a Gmsh .inp file."""
    nodes, inside = {}, False
    for line in inp_text.splitlines():
        if line.startswith("*"):
            inside = line.upper().startswith("*NODE")
            continue
        if inside and line.strip():
            parts = line.split(",")
            nodes[int(parts[0])] = (float(parts[1]), float(parts[2]), float(parts[3]))
    return nodes


def _id_lines(ids, per_line=10):
    ids = sorted(ids)
    return "\n".join(", ".join(str(i) for i in ids[k:k + per_line])
                     for k in range(0, len(ids), per_line))


def end_slabs(nodes: dict):
    """(fixed node ids, loaded node ids) at the two ends of the longest direction."""
    axis = max(range(3), key=lambda a: max(p[a] for p in nodes.values())
               - min(p[a] for p in nodes.values()))
    low = min(p[axis] for p in nodes.values())
    high = max(p[axis] for p in nodes.values())
    band = SLAB * (high - low)
    fixed = [i for i, p in nodes.items() if p[axis] <= low + band]
    loaded = [i for i, p in nodes.items() if p[axis] >= high - band]
    return fixed, loaded, axis


def solver_deck(mesh_file: str, nodes: dict) -> str:
    fixed, loaded, axis = end_slabs(nodes)
    if len(fixed) < 3 or not loaded:
        raise ValueError("probe mesh has too few end nodes")
    load_dof = 3 if axis != 2 else 1  # load across the longest direction (bending)
    per_node = TOTAL_FORCE_N / len(loaded)
    return "\n".join([
        "*INCLUDE, INPUT=%s" % mesh_file,
        "*NSET, NSET=FIXED", _id_lines(fixed),
        "*BOUNDARY", "FIXED, 1, 3",
        "*MATERIAL, NAME=STEEL", "*ELASTIC", "210000, 0.3",
        "*SOLID SECTION, ELSET=%s, MATERIAL=STEEL" % PROBE_ELSET,
        "*STEP", "*STATIC", "*CLOAD",
        "\n".join("%d, %d, %.9g" % (i, load_dof, per_node) for i in sorted(loaded)),
        "*NODE FILE", "U", "*END STEP", ""])
