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


def constraint_targets(doc, solid):
    """[(label, kind, sub-element names)] of FEM supports/loads acting on ``solid``."""
    found = []
    for obj in doc.Objects:
        if not obj.TypeId.startswith("Fem::Constraint") or getattr(obj, "Suppressed", False):
            continue
        subs = [s for target, names in (getattr(obj, "References", None) or [])
                if target is solid for s in names]
        if subs:
            found.append((obj.Label, obj.TypeId.replace("Fem::Constraint", "").lower(),
                          tuple(subs)))
    return found


def _set_region(doc, mesh, target, elements, size):
    """One assistant mesh region (finer size) on ``elements`` of ``target``."""
    import ObjectsFem  # type: ignore
    regions = [r for r in mesh.MeshRegionList if MARKER in r.PropertiesList]
    if not elements or size <= 0:
        for region in regions:
            doc.removeObject(region.Name)
        return None
    region = regions[0] if regions else ObjectsFem.makeMeshRegion(doc, mesh, size,
                                                                  "PartReview_Refine")
    if not regions:
        region.addProperty("App::PropertyString", MARKER, "PartReview",
                           "Created by the PartReview mesh assistant")
        setattr(region, MARKER, "refinement")
    region.CharacteristicLength = size
    region.References = [(target, tuple(elements))]
    return region


def set_regions(doc, mesh, target, groups):
    """Replace the assistant's refinement regions of ``mesh`` with one region per size.

    ``groups``: {size (mm): [face names of ``target``]}. User regions are kept."""
    import ObjectsFem  # type: ignore
    for region in [r for r in mesh.MeshRegionList if MARKER in r.PropertiesList]:
        doc.removeObject(region.Name)
    created = []
    for size, faces in groups.items():
        if not faces or size <= 0:
            continue
        region = ObjectsFem.makeMeshRegion(doc, mesh, size, "PartReview_Refine")
        region.addProperty("App::PropertyString", MARKER, "PartReview",
                           "Created by the PartReview mesh assistant")
        setattr(region, MARKER, "refinement")
        region.References = [(target, tuple(faces))]
        created.append(region)
    return created


def region_sizes(mesh):
    """{face: size} of the assistant's refinement regions of ``mesh``."""
    sizes = {}
    for region in mesh.MeshRegionList:
        if MARKER not in region.PropertiesList:
            continue
        size = region.CharacteristicLength.getValueAs("mm").Value
        for _target, faces in region.References:
            for face in faces:
                sizes[face] = min(size, sizes.get(face, size))
    return sizes


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


def gmsh_binary():
    """Gmsh executable as configured in FreeCAD's FEM preferences, else from PATH."""
    import shutil
    params = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/Gmsh")
    custom = "" if params.GetBool("UseStandardGmshLocation", True) else \
        params.GetString("gmshBinaryPath", "")
    return shutil.which(custom) if custom else shutil.which("gmsh")


def ccx_binary():
    """CalculiX executable as FreeCAD would use it (same rule as femtools.ccxtools)."""
    import shutil
    custom = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/Ccx").GetString(
        "ccxBinaryPath", "")
    return shutil.which(custom) if custom else shutil.which("ccx")


def ccx_threads():
    """OMP_NUM_THREADS as FreeCAD sets it for CalculiX."""
    wanted = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/Ccx").GetInt(
        "AnalysisNumCPUs", 1)
    return wanted if wanted > 1 else (os.cpu_count() or 1)


class WatchedProcess:
    """A child process with time limit and memory watchdog, polled by the caller."""

    def __init__(self, command, cwd, log_path, time_limit_s, memory_limit_mb, env=None):
        self.command, self.cwd, self.log_path, self.env = command, cwd, log_path, env
        self.time_limit, self.memory_limit = time_limit_s, memory_limit_mb
        self.elapsed = 0.0
        self.peak_mb = 0.0
        self.returncode = None
        self.stopped = ""  # "timeout" / "memory" / "cancelled" when killed
        self._process = None
        self._log = None
        self._t0 = 0.0

    def start(self):
        self._log = open(self.log_path, "w")
        self._process = subprocess.Popen(self.command, cwd=self.cwd, env=self.env,
                                         stdout=self._log, stderr=subprocess.STDOUT)
        self._t0 = time.monotonic()

    def poll(self):
        """True while running."""
        if self._process is None or self.returncode is not None or self.stopped:
            return False
        self.elapsed = time.monotonic() - self._t0
        self.peak_mb = max(self.peak_mb, _rss_mb(self._process.pid))
        code = self._process.poll()
        if code is None:
            if self.elapsed > self.time_limit:
                self.kill("timeout")
            elif self.peak_mb > self.memory_limit:
                self.kill("memory")
            return not self.stopped
        self.returncode = code
        self._log.close()
        return False

    def kill(self, reason="cancelled"):
        if self._process is not None and self._process.poll() is None:
            self._process.kill()
            self._process.wait()
        self.stopped = reason
        if self._log is not None and not self._log.closed:
            self._log.close()

    def log_text(self):
        with open(self.log_path, errors="replace") as fh:
            return fh.read()


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

    def job(self, option, time_limit_s, memory_limit_mb, refine=()):
        _apply_option(self.mesh, option)
        _set_region(self.doc, self.mesh, self.doc.getObject("Solid"), refine, option.local_size)
        self.doc.recompute()
        return GmshJob(self.mesh, time_limit_s, memory_limit_mb, load_into_object=False)

    def job_like(self, source_mesh, groups, time_limit_s, memory_limit_mb):
        """Try ``source_mesh``'s settings plus refinement ``groups`` ({size: faces})
        here first: a refined mesh reaches the user's document only if it fits."""
        for name in ("CharacteristicLengthMax", "CharacteristicLengthMin",
                     "MeshSizeFromCurvature", "ElementOrder", "SecondOrderLinear"):
            setattr(self.mesh, name, getattr(source_mesh, name))
        self.mesh.HighOrderOptimize = "None"
        set_regions(self.doc, self.mesh, self.doc.getObject("Solid"), groups)
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


def mesh_label(solid_obj):
    """Fixed name: updating the mesh never renames it (the chosen size is in MARKER)."""
    return "%s_Malha_PartReview" % solid_obj.Label


def create_mesh_object(doc, solid_obj, option, version, refine=()):
    """New Gmsh mesh object for ``solid_obj`` (undoable). Never touches existing meshes."""
    import ObjectsFem  # type: ignore
    doc.openTransaction("PartReview: mesh assistant")
    try:
        mesh = ObjectsFem.makeMeshGmsh(doc, "PartReview_Mesh")
        mesh.Label = mesh_label(solid_obj)
        mesh.Shape = solid_obj
        _apply_option(mesh, option)
        mesh.addProperty("App::PropertyString", MARKER, "PartReview",
                         "Created by the PartReview mesh assistant")
        setattr(mesh, MARKER, "%s %s" % (version, option.level.value))
        _set_region(doc, mesh, solid_obj, refine, option.local_size)
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


def assistant_mesh_for(doc, solid_obj):
    """The assistant's own mesh of ``solid_obj`` (the one in an analysis first), or None."""
    mine = [o for o in assistant_objects(doc) if o.isDerivedFrom("Fem::FemMeshObject")
            and getattr(getattr(o, "Shape", None), "Name", None) == solid_obj.Name]
    grouped = {o.Name for a in analyses(doc) for o in a.Group}
    mine.sort(key=lambda o: o.Name not in grouped)
    return mine[0] if mine else None


def create_or_update_mesh(doc, solid_obj, option, version, refine=()):
    """(mesh, updated). The assistant keeps ONE mesh per part: running it again
    updates that mesh (undoable) instead of piling up new objects. Meshes made by
    the user are never touched (then a new one is created next to them)."""
    mesh = assistant_mesh_for(doc, solid_obj)
    if mesh is None:
        return create_mesh_object(doc, solid_obj, option, version, refine), False
    doc.openTransaction("PartReview: mesh assistant")
    try:
        mesh.Label = mesh_label(solid_obj)
        _apply_option(mesh, option)
        setattr(mesh, MARKER, "%s %s" % (version, option.level.value))
        _set_region(doc, mesh, solid_obj, refine, option.local_size)
        doc.recompute()
    except Exception:
        doc.abortTransaction()
        raise
    doc.commitTransaction()
    return mesh, True


def has_results(doc):
    return any(o.isDerivedFrom("Fem::FemResultObject") for o in doc.Objects)


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


class ProbeJob:
    """CalculiX on a trial mesh of the user's part (generic support and load), to
    measure solver memory and time on this computer. Uses the trial's own Gmsh
    settings, re-meshed into a CalculiX .inp with only the volume."""

    MESH, SOLVE, DONE, FAILED, CANCELLED = "mesh", "solve", "done", "failed", "cancelled"

    def __init__(self, gmsh_job, time_limit_s, memory_limit_mb):
        from ..domain import solver_probe as sp
        self._sp = sp
        self.workdir = os.path.dirname(gmsh_job.tools.temp_file_geo)
        with open(gmsh_job.tools.temp_file_geo) as fh:
            geo = fh.read()
        with open(os.path.join(self.workdir, "probe.geo"), "w") as fh:
            fh.write(sp.probe_geo(geo, "probe_mesh.inp"))
        self.gmsh, self.ccx = gmsh_job.tools.gmsh_bin, ccx_binary()
        if not self.ccx:
            raise FileNotFoundError("ccx")
        self.time_limit, self.memory_limit = time_limit_s, memory_limit_mb
        self.env = dict(os.environ, OMP_NUM_THREADS=str(ccx_threads()))
        self.state = None
        self.process = None
        self.nodes = 0
        self.seconds = 0.0
        self.peak_mb = 0.0
        self.mesh_seconds = 0.0
        self.reason = ""

    @property
    def elapsed(self):
        return self.mesh_seconds + (self.process.elapsed if self.process else 0.0)

    def start(self):
        self.process = WatchedProcess([self.gmsh, "-", "probe.geo"], self.workdir,
                                      os.path.join(self.workdir, "probe_gmsh.log"),
                                      self.time_limit, self.memory_limit)
        self.process.start()
        self.state = self.MESH

    def poll(self):
        if self.state not in (self.MESH, self.SOLVE):
            return self.state
        if self.process.poll():
            return self.state
        if self.process.stopped or self.process.returncode != 0:
            self.reason = self.process.stopped or "failed"
            self.state = self.CANCELLED if self.reason == "cancelled" else self.FAILED
            return self.state
        if self.state == self.MESH:
            self.mesh_seconds = self.process.elapsed
            with open(os.path.join(self.workdir, "probe_mesh.inp")) as fh:
                nodes = self._sp.parse_nodes(fh.read())
            self.nodes = len(nodes)
            with open(os.path.join(self.workdir, "probe.inp"), "w") as fh:
                fh.write(self._sp.solver_deck("probe_mesh.inp", nodes))
            self.process = WatchedProcess([self.ccx, "-i", "probe"], self.workdir,
                                          os.path.join(self.workdir, "probe_ccx.log"),
                                          self.time_limit, self.memory_limit, self.env)
            self.process.start()
            self.state = self.SOLVE
            return self.state
        if "Job finished" not in self.process.log_text():
            self.reason = "failed"
            self.state = self.FAILED
            return self.state
        self.seconds, self.peak_mb = self.process.elapsed, self.process.peak_mb
        for name in ("probe.frd", "probe.dat", "probe.sta", "probe.cvg", "probe.12d",
                     "probe_mesh.inp", "spooles.out"):  # results are not needed: keep disk free
            path = os.path.join(self.workdir, name)
            if os.path.isfile(path):
                os.remove(path)
        self.state = self.DONE
        return self.state

    def cancel(self):
        if self.process is not None:
            self.process.kill()
        self.reason = "cancelled"
        self.state = self.CANCELLED
