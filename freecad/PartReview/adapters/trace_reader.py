# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Collect traceability data from FreeCAD and the file on disk (phase 6a, step e)."""

import datetime
import hashlib
import os
import platform

import FreeCAD as App  # type: ignore

from ..domain.trace import Traceability

SOLVER_SETTINGS = ("AnalysisType", "GeometricalNonlinearity", "MaterialNonlinearity",
                   "MatrixSolverType")
MESHER_SETTINGS = ("ElementOrder", "CharacteristicLengthMax", "CharacteristicLengthMin",
                   "Algorithm2D", "Algorithm3D", "SecondOrderLinear", "MeshSizeFromCurvature",
                   "OptimizeStd", "Fineness", "GrowthRate")
MESHERS = (("Gmsh", "Gmsh"), ("Netgen", "Netgen"))


def freecad_version():
    v = App.Version()
    text = ".".join(v[:3])
    extra = []
    if len(v) > 3 and v[3]:
        extra.append("build %s" % v[3].split()[0])
    if len(v) > 7 and v[7]:
        extra.append("commit %s" % v[7][:8])
    return "%s (%s)" % (text, ", ".join(extra)) if extra else text


def file_sha256(path, chunk=1 << 20):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def _value(obj, name):
    value = getattr(obj, name)
    return value.UserString if hasattr(value, "UserString") else str(value)


def _settings(obj, names):
    return tuple((n, _value(obj, n)) for n in names if obj is not None and hasattr(obj, n))


def collect(doc, result_obj, analysis, solver_name, analysis_type, tool_version, unsaved):
    path = doc.FileName or ""
    sha, modified = "", None
    if path and os.path.isfile(path):
        sha = file_sha256(path)
        modified = datetime.datetime.fromtimestamp(os.path.getmtime(path))
    solver = next((o for o in analysis.Group if o.TypeId.startswith("Fem::FemSolverObject")), None)
    mesh = next((o for o in analysis.Group if o.TypeId.startswith("Fem::FemMeshShape")), None)
    mesher = ""
    if mesh is not None:
        kind = getattr(getattr(mesh, "Proxy", None), "Type", "") or mesh.TypeId
        mesher = next((nice for key, nice in MESHERS if key in kind), kind)
        mesher = "%s (%s)" % (mesher, mesh.Label)
    return Traceability(
        tool_version=tool_version,
        freecad_version=freecad_version(),
        generated_at=datetime.datetime.now().replace(microsecond=0),
        platform=platform.platform(terse=True),
        python_version=platform.python_version(),
        file_name=os.path.basename(path) or doc.Label,
        file_path=path,
        file_sha256=sha,
        file_modified=modified.replace(microsecond=0) if modified else None,
        unsaved_changes=bool(unsaved),
        result_name=result_obj.Name,
        result_label=result_obj.Label,
        solver=solver_name,
        analysis_type=analysis_type,
        solver_settings=_settings(solver, SOLVER_SETTINGS),
        mesher=mesher,
        mesher_settings=_settings(mesh, MESHER_SETTINGS),
    )
