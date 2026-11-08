# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Create the assistant's Gmsh mesh object and run Gmsh safely (CLAUDE.md rules 8, 9, 11).

Gmsh always runs as a separate process with a time limit and a memory watchdog
(read from /proc on Linux; elsewhere only the time limit applies). Nothing here
blocks the GUI: the panel calls ``poll()`` from a timer.
"""

import os
import subprocess
import time

import FreeCAD as App  # type: ignore

from ..domain.gmsh_log import GmshRun, parse_gmsh_log

MARKER = "PartReviewAssistant"  # property on every object the assistant creates


def _apply_option(mesh, option):
    mesh.CharacteristicLengthMax = option.max_size
    mesh.CharacteristicLengthMin = option.min_size
    mesh.MeshSizeFromCurvature = option.curvature
    mesh.ElementOrder = option.order
    mesh.SecondOrderLinear = option.straight_edges
    mesh.HighOrderOptimize = "None"  # "Optimization" aborted Gmsh in FreeCAD 1.1.4


def _rss_mb(pid):
    try:
        with open("/proc/%d/status" % pid) as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except OSError:
        return 0.0
    return 0.0


class GmshJob:
    """One Gmsh run for a Gmsh mesh object, polled by the caller."""

    RUNNING, DONE, FAILED, TIMEOUT, MEMORY, CANCELLED = (
        "running", "done", "failed", "timeout", "memory", "cancelled")

    def __init__(self, mesh_obj, time_limit_s, memory_limit_mb, load_into_object):
        from femmesh.gmshtools import GmshTools  # type: ignore
        self.mesh_obj = mesh_obj
        self.tools = GmshTools(mesh_obj)
        self.tools.prepare()  # writes .brep + .geo in a temporary folder
        self.log_path = os.path.join(os.path.dirname(self.tools.temp_file_geo), "gmsh.log")
        self.time_limit = time_limit_s
        self.memory_limit = memory_limit_mb
        self.load = load_into_object
        self.state = None
        self.peak_mb = 0.0
        self.started = 0.0
        self.elapsed = 0.0
        self.run = GmshRun()
        self._process = None
        self._log = None

    def start(self):
        self._log = open(self.log_path, "w")
        self._process = subprocess.Popen(
            [self.tools.gmsh_bin, "-v", "4", "-", self.tools.temp_file_geo],
            stdout=self._log, stderr=subprocess.STDOUT)
        self.started = time.monotonic()
        self.state = self.RUNNING

    def poll(self):
        """Advance the job; returns the state."""
        if self.state != self.RUNNING:
            return self.state
        self.elapsed = time.monotonic() - self.started
        self.peak_mb = max(self.peak_mb, _rss_mb(self._process.pid))
        if self._process.poll() is None:
            if self.elapsed > self.time_limit:
                self._stop(self.TIMEOUT)
            elif self.peak_mb > self.memory_limit:
                self._stop(self.MEMORY)
            return self.state
        self._log.close()
        self.run = parse_gmsh_log(self._read_log())
        if self._process.returncode == 0 and self.run.finished:
            if self.load:  # undoable, like every write to the user's document (rule 9)
                doc = self.mesh_obj.Document
                doc.openTransaction("PartReview: generate mesh")
                self.tools.update_properties()  # mesh_obj.FemMesh = Fem.read(...)
                doc.commitTransaction()
            self.state = self.DONE
        else:
            self.state = self.FAILED
        return self.state

    def cancel(self):
        if self.state == self.RUNNING:
            self._stop(self.CANCELLED)

    def _stop(self, state):
        self._process.kill()
        self._process.wait()
        self._log.close()
        self.run = parse_gmsh_log(self._read_log())
        self.state = state

    def _read_log(self):
        with open(self.log_path, errors="replace") as fh:
            return fh.read()

    def log_tail(self, lines=15):
        return "\n".join(self._read_log().splitlines()[-lines:])


class TrialDocument:
    """Hidden scratch document: try mesh options without touching the user's file."""

    def __init__(self, shape):
        import ObjectsFem  # type: ignore
        active = App.ActiveDocument
        self.doc = App.newDocument("PartReviewMeshTrial", hidden=True, temp=True)
        part = self.doc.addObject("Part::Feature", "Solid")
        part.Shape = shape
        self.mesh = ObjectsFem.makeMeshGmsh(self.doc, "TrialMesh")
        self.mesh.Shape = part
        if active is not None:
            App.setActiveDocument(active.Name)

    def job(self, option, time_limit_s, memory_limit_mb):
        _apply_option(self.mesh, option)
        self.doc.recompute()
        return GmshJob(self.mesh, time_limit_s, memory_limit_mb, load_into_object=False)

    def close(self):
        App.closeDocument(self.doc.Name)


def analyses(doc):
    return [o for o in doc.Objects if o.TypeId == "Fem::FemAnalysis"]


def analysis_meshes(analysis):
    """Solver meshes of an analysis (result meshes excluded)."""
    results = [getattr(o, "Mesh", None) for o in analysis.Group if hasattr(o, "Mesh")
               and o.isDerivedFrom("Fem::FemResultObject")]
    return [o for o in analysis.Group if o.isDerivedFrom("Fem::FemMeshObject")
            and not any(o is r for r in results)]


def create_mesh_object(doc, solid_obj, option, version):
    """New Gmsh mesh object for ``solid_obj`` (undoable). Never touches existing meshes."""
    import ObjectsFem  # type: ignore
    doc.openTransaction("PartReview: mesh assistant")
    try:
        mesh = ObjectsFem.makeMeshGmsh(doc, "PartReview_Mesh")
        mesh.Label = "%s_Malha_%s" % (solid_obj.Label, option.level.value)
        mesh.Shape = solid_obj
        _apply_option(mesh, option)
        mesh.addProperty("App::PropertyString", MARKER, "PartReview",
                         "Created by the PartReview mesh assistant")
        setattr(mesh, MARKER, "%s %s" % (version, option.level.value))
        found = analyses(doc)
        # Into the analysis only when it is the only one and has no mesh yet: FreeCAD's
        # CalculiX refuses an analysis with two meshes, and the user's mesh is never touched.
        if len(found) == 1 and not analysis_meshes(found[0]):
            found[0].addObject(mesh)
        doc.recompute()
    except Exception:
        doc.abortTransaction()
        raise
    doc.commitTransaction()
    return mesh


def assistant_objects(doc):
    return [o for o in doc.Objects if MARKER in o.PropertiesList]


def remove_assistant_objects(doc):
    """Delete only what the assistant created (undoable). Returns how many."""
    objs = assistant_objects(doc)
    if not objs:
        return 0
    doc.openTransaction("PartReview: remove assistant meshes")
    for obj in objs:
        doc.removeObject(obj.Name)
    doc.commitTransaction()
    doc.recompute()
    return len(objs)
