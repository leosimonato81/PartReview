# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""'Optimise the mesh by the error' (decision 008): run the user's own analysis
with FreeCAD's CalculiX tools, read the estimated error per element and map it to
the CAD faces. Uses calculation results by design, only after the user's click.
"""

import os
import tempfile

import FreeCAD as App  # type: ignore
import numpy as np
import Part  # type: ignore

from . import fem_reader
from .error_estimator import estimate
from .mesh_runner import WatchedProcess, analyses, ccx_threads

_CONSTRAINT_PREFIX = "Fem::Constraint"


class PrerequisiteError(Exception):
    """The analysis cannot be solved as it is (message from FreeCAD's checks)."""


def analysis_of(doc, mesh):
    for analysis in analyses(doc):
        if any(o.Name == mesh.Name for o in analysis.Group):
            return analysis
    return None


def solver_of(analysis):
    for obj in analysis.Group:
        if obj.TypeId.startswith("Fem::FemSolverObject"):
            return obj
    return None


def singular_faces(doc, solid):
    """Faces next to supports/loads on edges or vertices: the stress there is
    theoretically infinite and the error does not converge (left out of the
    refinement and of the 'regular' maximum stress)."""
    shape = solid.Shape
    faces = list(enumerate(shape.Faces, start=1))
    found = set()
    for obj in doc.Objects:
        if not obj.TypeId.startswith(_CONSTRAINT_PREFIX) or getattr(obj, "Suppressed", False):
            continue
        for target, subs in getattr(obj, "References", None) or []:
            if getattr(target, "Name", None) != solid.Name:
                continue
            for sub in subs:
                if not sub.startswith(("Edge", "Vertex")):
                    continue
                element = shape.getElement(sub)
                for index, face in faces:
                    if any(element.isSame(e) for e in (face.Edges if sub.startswith("Edge")
                                                       else face.Vertexes)):
                        found.add("Face%d" % index)
    return found


def support_faces(doc, solid):
    """Faces of fixed supports: their boundary edges are clamped corners, where the
    stress also grows with refinement. Used only for the 'regular' stress figure."""
    found = set()
    for obj in doc.Objects:
        if obj.TypeId != "Fem::ConstraintFixed" or getattr(obj, "Suppressed", False):
            continue
        for target, subs in getattr(obj, "References", None) or []:
            if getattr(target, "Name", None) == solid.Name:
                found.update(s for s in subs if s.startswith("Face"))
    return found


def face_nodes(mesh_obj):
    """{face name: set of node ids} from the Gmsh node groups ('FaceN_Nodes')."""
    fm = mesh_obj.FemMesh
    out = {}
    for group in fm.Groups:
        name = fm.getGroupName(group)
        if name.startswith("Face") and name.endswith("_Nodes") and \
                fm.getGroupElementType(group) == "Node":
            out[name[:-6]] = set(fm.getGroupElements(group))
    return out


class SolveJob:
    """Write the CalculiX input (FreeCAD's writer), run CalculiX as a watched process,
    then replace the results. Old results stay until the new run succeeded."""

    RUNNING, DONE, FAILED, CANCELLED = "running", "done", "failed", "cancelled"

    def __init__(self, analysis, time_limit_s, memory_limit_mb):
        from femtools.ccxtools import FemToolsCcx  # type: ignore
        self.fea = FemToolsCcx(analysis, solver_of(analysis))
        self.time_limit, self.memory_limit = time_limit_s, memory_limit_mb
        self.workdir = tempfile.mkdtemp(prefix="partreview_opt_")
        self.process = None
        self.state = None
        self.reason = ""
        self.seconds = 0.0
        self.peak_mb = 0.0

    @property
    def elapsed(self):
        return self.process.elapsed if self.process is not None else 0.0

    def start(self):
        fea = self.fea
        fea.update_objects()
        fea.setup_working_dir(self.workdir, create=True)
        message = fea.check_prerequisites()
        if message:
            raise PrerequisiteError(message)
        fea.write_inp_file()  # FreeCAD's own CalculiX writer (constraints, material)
        fea.setup_ccx()
        base = os.path.splitext(os.path.basename(fea.inp_file_name))[0]
        env = dict(os.environ, OMP_NUM_THREADS=str(ccx_threads()))
        self.process = WatchedProcess([fea.ccx_binary, "-i", base], fea.working_dir,
                                      os.path.join(self.workdir, "ccx.log"),
                                      self.time_limit, self.memory_limit, env)
        self.process.start()
        self.state = self.RUNNING

    def poll(self):
        if self.state != self.RUNNING:
            return self.state
        if self.process.poll():
            return self.state
        self.seconds, self.peak_mb = self.process.elapsed, self.process.peak_mb
        if self.process.stopped:
            self.reason = self.process.stopped
            self.state = self.CANCELLED if self.reason == "cancelled" else self.FAILED
            return self.state
        if "Job finished" not in self.process.log_text():
            self.reason = "failed"
            self.state = self.FAILED
            return self.state
        self.fea.purge_results()  # only now: the new results are on disk
        self.fea.load_results()
        self.state = self.DONE
        return self.state

    def cancel(self):
        if self.process is not None:
            self.process.kill()
        self.reason = "cancelled"
        self.state = self.CANCELLED

    def log_tail(self, lines=20):
        if self.process is None:
            return ""
        return "\n".join(self.process.log_text().splitlines()[-lines:])


def _element_energy(zz):
    """||u_h||^2 per element, from the local relative error eta_e and ||e||^2:
    eta^2 = e^2 / (u^2 + e^2)  ->  u^2 = e^2 (1 - eta^2) / eta^2."""
    eta2 = np.maximum(zz.element_relative ** 2, 1e-300)
    return zz.element_error_sq * (1.0 - eta2) / eta2


def latest_result(analysis):
    results = [o for o in analysis.Group if fem_reader.is_mechanical_result(o)]
    return results[-1] if results else None


def error_by_element(analysis, mesh_obj, singular, stress_excluded=()):
    """Estimated error and what the refinement needs, from the latest result.

    Returns dict with: error (global, 0..1), nodes, ratios input (error_sq per
    element), energy_sq, element sizes (mm), element faces, max stress (whole
    part and away from singular faces), max displacement."""
    result = latest_result(analysis)
    if result is None:
        raise PrerequisiteError("no result")
    constants = fem_reader.elastic_constants(analysis)
    if constants is None:
        raise PrerequisiteError("material")
    result_mesh = result.Mesh
    positions = {n: (v.x, v.y, v.z) for n, v in result_mesh.FemMesh.Nodes.items()}
    elements = fem_reader.read_volume_elements(result_mesh)
    zz = estimate(positions, elements, fem_reader.read_displacement_vectors(result), *constants)
    energy_e = _element_energy(zz)
    ids = sorted(positions)
    index = {n: i for i, n in enumerate(ids)}
    coords = np.array([positions[n] for n in ids])
    corners = np.array([[index[n] for n in e[:4]] for e in elements])
    pairs = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))
    sizes = np.mean([np.linalg.norm(coords[corners[:, a]] - coords[corners[:, b]], axis=1)
                     for a, b in pairs], axis=0)
    by_face = face_nodes(mesh_obj)
    node_faces = {}
    for face, nodes in by_face.items():
        for n in nodes:
            node_faces.setdefault(n, []).append(face)
    element_faces = []
    for e in elements:
        counts = {}
        for n in e:
            for face in node_faces.get(n, ()):
                counts[face] = counts.get(face, 0) + 1
        element_faces.append(tuple(f for f, c in counts.items() if c >= 3))  # a whole side
    # Error AWAY from supports and singular regions (Saint-Venant: idealised rigid
    # supports and line/point loads disturb the solution only locally, and there the
    # error does not converge). Used as the optimisation target.
    skip_faces = set(singular) | set(stress_excluded)
    regular = [i for i, faces in enumerate(element_faces) if not set(faces) & skip_faces]
    err_r = float(np.sum(zz.element_error_sq[regular])) if regular else 0.0
    ene_r = float(np.sum(energy_e[regular])) if regular else 0.0
    error_regular = (err_r / (ene_r + err_r)) ** 0.5 if ene_r + err_r > 0 else zz.relative_error
    stress = dict(zip(result.NodeNumbers, result.vonMises))
    skip = set(singular) | set(stress_excluded)
    singular_nodes = set().union(*(by_face.get(f, set()) for f in skip)) if skip else set()
    regular = [v for n, v in stress.items() if n not in singular_nodes]
    return {"error": zz.relative_error, "error_regular": error_regular,
            "nodes": len(positions),
            "error_sq": zz.element_error_sq.tolist(), "energy_sq": zz.energy_norm_sq,
            "sizes": sizes.tolist(), "faces": element_faces,
            "max_stress": max(stress.values()) if stress else 0.0,
            "max_stress_regular": max(regular) if regular else 0.0,
            "max_displacement": max(result.DisplacementLengths) if result.DisplacementLengths
            else 0.0}


HISTORY = "PartReviewConvergence"  # JSON list of passes, on the optimised mesh


def save_history(mesh_obj, passes):
    """Store the passes on the mesh (caller holds an undoable transaction), so the
    report can show the convergence study of the mesh that made the results."""
    import json
    if not hasattr(mesh_obj, HISTORY):
        mesh_obj.addProperty("App::PropertyString", HISTORY, "PartReview",
                             "Convergence study of 'Optimise mesh by the error'")
        mesh_obj.setPropertyStatus(HISTORY, ["ReadOnly"])
    rows = [{"nodes": p.nodes, "error": p.error, "global_error": p.global_error,
             "max_stress_regular": p.max_stress_regular,
             "max_displacement": p.max_displacement} for p in passes]
    setattr(mesh_obj, HISTORY, json.dumps(rows))


def read_history(analysis, result_nodes):
    """[ConvergencePass] stored on the analysis' mesh, or [] when there is none or
    it does not belong to the current results (last pass node count differs:
    the mesh was changed after optimising)."""
    import json
    from ..domain.quality import ConvergencePass
    for obj in analysis.Group:
        text = getattr(obj, HISTORY, "") if obj.isDerivedFrom("Fem::FemMeshObject") else ""
        if not text:
            continue
        try:
            rows = [ConvergencePass(int(r["nodes"]), float(r["error"]),
                                    float(r["global_error"]), float(r["max_stress_regular"]),
                                    float(r["max_displacement"])) for r in json.loads(text)]
        except (ValueError, KeyError, TypeError) as err:
            App.Console.PrintWarning("PartReview: convergence history ignored: %s\n" % err)
            return []
        return rows if rows and rows[-1].nodes == result_nodes else []
    return []
