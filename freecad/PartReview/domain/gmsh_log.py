# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Read what Gmsh reports about a mesh run (pure, no Qt)."""

import re
from dataclasses import dataclass

_COUNTS = re.compile(r"Info\s*:\s*(\d+) nodes (\d+) elements")
_INVERTED = re.compile(r"Volume mesh: worst distortion = \S+ \(avg = \S+, (\d+) elements with jac\. < 0\)")
_STAGE = re.compile(r"Done (meshing \dD|optimizing mesh|meshing order 2)\s*\(Wall ([\d.eE+-]+)s")
_ERROR = re.compile(r"^(Error\s*:.*)$", re.MULTILINE)


@dataclass(frozen=True)
class GmshRun:
    nodes: int = 0  # 0 when Gmsh did not finish
    elements: int = 0
    inverted: int = 0  # 2nd-order volume elements with negative Jacobian (CalculiX refuses)
    stage_seconds: tuple = ()  # (("meshing 2D", 0.97), ...)
    errors: tuple = ()

    @property
    def finished(self) -> bool:
        return self.nodes > 0 and not self.errors


def parse_gmsh_log(text: str) -> GmshRun:
    counts = _COUNTS.findall(text)
    nodes, elements = (int(counts[-1][0]), int(counts[-1][1])) if counts else (0, 0)
    found = _INVERTED.findall(text)
    inverted = int(found[-1]) if found else 0  # last report = final mesh
    stages = tuple((name, float(seconds)) for name, seconds in _STAGE.findall(text))
    errors = tuple(e.strip() for e in _ERROR.findall(text))
    return GmshRun(nodes, elements, inverted, stages, errors)


_THREADS = re.compile(r"^\s*General\.NumThreads\s*=.*$", re.MULTILINE)


def single_thread(geo: str) -> str:
    """Gmsh input (.geo) set to mesh with ONE thread.

    FreeCAD writes General.NumThreads from its preference (default: every core).
    With several threads Gmsh gave a different mesh on each run of the same input
    and, now and then, a flat tetrahedron that CalculiX refused (A1b, 2026-11-11);
    with one thread the same input gave the same mesh every time, in the same
    time. So a mesh the assistant tested is the mesh it creates."""
    line = "General.NumThreads = 1;"
    if _THREADS.search(geo):
        return _THREADS.sub(line, geo)
    return line + "\n" + geo

