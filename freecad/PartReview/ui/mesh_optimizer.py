# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""'Optimise the mesh by the error' task panel (decision 008). Thin: rules in domain/.

Loop: solve the user's analysis (FreeCAD's CalculiX tools, watched process) ->
estimated error per element -> finer size on the CAD faces where it is too high ->
try the refined mesh in a hidden document -> apply only if memory and time fit ->
solve again. Stops at the target error, the computer's limits, stagnation
(singularities) or after a few passes. Uses results by design, only on click.
"""

import time

import FreeCAD as App  # type: ignore
import FreeCADGui as Gui  # type: ignore
from PySide6.QtCore import QTimer  # type: ignore
from PySide6.QtWidgets import (  # type: ignore
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..adapters import machine_calibration, mesh_runner, optimizer
from ..adapters.machine import machine_profile
from ..domain import adaptive as ad
from ..domain import mesh_plan as mp
from ..domain import mesh_texts as mt
from ..domain.i18n import Translator
from ..domain.mesh_budget import TIGHT_FRACTION
from ..domain.solver_model import SolverSample, format_duration, speed_factor
from .mesh_assistant import _button
from .report_dialog import ui_language

TARGETS = (0.10, 0.05, 0.02)
TIME_LIMITS = (300.0, 600.0, 1200.0)
SOLVE_TIME_LIMIT_S = 1800  # hard stop of one CalculiX run
SOLVE_MEMORY_SHARE = 0.8  # hard stop (the plan keeps each run within 60 %)
GMSH_TIME_LIMIT_S = 300
GMSH_MEMORY_SHARE = 0.7
COLUMNS = ("mo.col.pass", "mo.col.nodes", "mo.col.error", "mo.col.global", "mo.col.stress",
           "mo.col.disp", "mo.col.time", "mo.col.memory")


class MeshOptimizerPanel:
    def __init__(self, doc):
        self.doc = doc
        self.tr = Translator(ui_language())
        t = self.tr.t
        self.machine = machine_profile()
        self.history_samples, _ = machine_calibration.load(self.machine)
        self.candidates = self._find_setups()
        self.mesh, self.solid, self.analysis = self._preselected()
        self.singular = set()
        self.stress_excluded = set()
        self.passes = []  # adaptive.Pass
        self.samples = []  # SolverSample of each real solve
        self.job = None
        self.stage = ""
        self.trial = None
        self.pending_groups = None
        self.started = 0.0
        self.pass_started = 0.0
        self.stop_key = ""

        self.form = QWidget()
        self.form.setWindowTitle(t("mo.title"))
        layout = QVBoxLayout(self.form)
        intro = QLabel(t("mo.intro"))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        setup = QGroupBox(t("mo.group.setup"))
        form = QFormLayout(setup)
        self.mesh_combo = None
        if len(self.candidates) > 1:  # several parts with an assistant mesh: user picks
            self.mesh_combo = QComboBox()
            for mesh, solid, analysis in self.candidates:
                self.mesh_combo.addItem("%s (%s)" % (solid.Label, analysis.Label), mesh.Name)
            self.mesh_combo.setCurrentIndex(
                [c[0].Name for c in self.candidates].index(self.mesh.Name))
            self.mesh_combo.currentIndexChanged.connect(self._mesh_chosen)
            form.addRow("<b>%s</b>" % t("mo.choose"), self.mesh_combo)
        self.setup_labels = {}
        for key in ("mo.analysis", "mo.part", "mo.mesh"):
            label = QLabel()
            label.setWordWrap(True)
            form.addRow("<b>%s</b>" % t(key), label)
            self.setup_labels[key] = label
        self.notes = QListWidget()
        self.notes.setWordWrap(True)
        self.notes.setMaximumHeight(110)
        form.addRow(self.notes)
        layout.addWidget(setup)

        goal = QGroupBox(t("mo.group.goal"))
        goal_form = QFormLayout(goal)
        self.target_box = QComboBox()
        for target in TARGETS:
            self.target_box.addItem(t("mo.target_value", value=int(round(100 * target))), target)
        self.target_box.setCurrentIndex(1)  # 5 %
        self.time_box = QComboBox()
        for seconds in TIME_LIMITS:
            self.time_box.addItem(t("mo.time_value", minutes=int(seconds // 60)), seconds)
        self.time_box.setCurrentIndex(1)  # 10 min
        goal_form.addRow(t("mo.target"), self.target_box)
        goal_form.addRow(t("mo.time_limit"), self.time_box)
        goal_note = QLabel(t("mo.goal_note"))
        goal_note.setWordWrap(True)
        goal_form.addRow(goal_note)
        self.forecast = QLabel(t("mo.fc.before"))  # which targets fit THIS computer
        self.forecast.setWordWrap(True)
        goal_form.addRow("<b>%s</b>" % t("mo.fc.title"), self.forecast)
        layout.addWidget(goal)

        run = QGroupBox(t("mo.group.run"))
        run_layout = QVBoxLayout(run)
        self.start_button = _button(t("mo.start"), QStyle.SP_MediaPlay, self.start, primary=True,
                                    tip=t("mo.start_tip"))
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.cancel_button = _button(t("ma.cancel"), QStyle.SP_DialogCancelButton, self.cancel)
        row = QHBoxLayout()
        row.addWidget(self.progress, 1)
        row.addWidget(self.cancel_button)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([t(c) for c in COLUMNS])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.setMinimumHeight(140)
        run_layout.addWidget(self.start_button)
        run_layout.addWidget(self.status)
        run_layout.addLayout(row)
        run_layout.addWidget(self.table)
        layout.addWidget(run)
        layout.addStretch(1)

        self.timer = QTimer()
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._tick)
        self._fill_setup()
        self._set_busy(False)

    # --- FreeCAD task panel protocol ------------------------------------------------

    def getStandardButtons(self):
        return QDialogButtonBox.StandardButton.Close

    def reject(self):
        self._cleanup()
        Gui.Control.closeDialog()
        return True

    def accept(self):
        return self.reject()

    # --- setup ------------------------------------------------------------------------

    def _find_setups(self):
        """[(assistant mesh, solid, analysis)]: the optimiser refines the assistant's
        own meshes that are in an analysis (user meshes are never changed)."""
        found = []
        for obj in mesh_runner.assistant_objects(self.doc):
            if obj.isDerivedFrom("Fem::FemMeshObject") and getattr(obj, "Shape", None):
                analysis = optimizer.analysis_of(self.doc, obj)
                if analysis is not None:
                    found.append((obj, obj.Shape, analysis))
        return found

    def _preselected(self):
        """The candidate selected in the tree (its mesh, part or analysis), else the
        first one."""
        if not self.candidates:
            return None, None, None
        names = {o.Name for o in Gui.Selection.getSelection(self.doc.Name)}
        for candidate in self.candidates:
            if names & {candidate[0].Name, candidate[1].Name, candidate[2].Name}:
                return candidate
        return self.candidates[0]

    def _mesh_chosen(self, index):
        if self.job is not None:
            return
        self.mesh, self.solid, self.analysis = self.candidates[index]
        self.notes.clear()
        self.table.setRowCount(0)
        self.passes, self.samples = [], []
        self.forecast.setText(self.tr.t("mo.fc.before"))
        self.status.setText("")
        self._fill_setup()

    def _fill_setup(self):
        t = self.tr.t
        labels = self.setup_labels
        if self.mesh is None:
            for label in labels.values():
                label.setText("—")
            self.notes.addItem(QListWidgetItem("⚠ " + t("mo.need_assistant_mesh")))
            self.start_button.setEnabled(False)
            return
        labels["mo.analysis"].setText(self.analysis.Label)
        labels["mo.part"].setText(self.solid.Label)
        labels["mo.mesh"].setText(t("mo.mesh_value", label=self.mesh.Label,
                                    nodes=self.tr.integer(self.mesh.FemMesh.NodeCount)))
        self.singular = optimizer.singular_faces(self.doc, self.solid)
        self.stress_excluded = optimizer.support_faces(self.doc, self.solid)
        if self.singular:
            self.notes.addItem(QListWidgetItem("⚠ " + t(
                "mo.singular", faces=", ".join(sorted(self.singular, key=lambda f: int(f[4:]))))))
        if self.stress_excluded:
            self.notes.addItem(QListWidgetItem("ℹ " + t("mo.corners")))
        self.notes.addItem(QListWidgetItem("ℹ " + t("mo.uses_results")))

    # --- actions ----------------------------------------------------------------------

    def start(self):
        if self.mesh is None or self.job is not None:
            return
        self.machine = machine_profile()
        self.passes, self.samples = [], []
        self.table.setRowCount(0)
        self.stop_key = ""
        self.started = time.monotonic()
        if self.mesh.FemMesh.NodeCount == 0:  # mesh object not generated yet
            self._start_job("mesh", mesh_runner.GmshJob(
                self.mesh, GMSH_TIME_LIMIT_S, GMSH_MEMORY_SHARE * self.machine.available_mb,
                load_into_object=True))
        elif self._first_solve_fits():
            self._start_solve()

    def _first_solve_fits(self):
        """Pass 0 is checked too: memory depends on the mesh, not on the computer;
        before any solve of this part it is a band (thin-walled .. compact parts)."""
        nodes = self.mesh.FemMesh.NodeCount
        model = mp.part_model(self.samples)
        free = self.machine.available_mb
        if mp.is_hopeless(model, nodes, free, TIGHT_FRACTION):  # even the optimistic side
            self._finish("first_too_big", nodes=nodes,
                         memory=mt.memory(self.tr, model.memory_low(nodes)))
            return False
        return True

    def cancel(self):
        if self.job is not None:
            self.job.cancel()

    # --- loop -------------------------------------------------------------------------

    def _start_job(self, stage, job):
        self.stage, self.job = stage, job
        job.start()
        self._set_busy(True)
        self._show_progress()
        self.timer.start()

    def _start_solve(self):
        t = self.tr.t
        self.pass_started = time.monotonic()
        self.status.setText(t("mo.writing"))
        QApplication.processEvents()
        job = optimizer.SolveJob(self.analysis, SOLVE_TIME_LIMIT_S,
                                 SOLVE_MEMORY_SHARE * self.machine.available_mb)
        try:
            self._start_job("solve", job)
        except optimizer.PrerequisiteError as err:
            self._finish("prerequisite", str(err))

    def _tick(self):
        job = self.job
        if job is None:
            self.timer.stop()
            return
        state = job.poll()
        if state in ("running", "mesh", "solve"):
            self._show_progress()
            return
        self.timer.stop()
        self.job = None
        if state != job.DONE:
            reason = getattr(job, "reason", "") or state
            process = getattr(job, "process", None)
            peak = mt.memory(self.tr, process.peak_mb) if process is not None else ""
            if reason in ("memory", "timeout"):  # the watchdog protected the computer
                self._finish("killed_" + reason, memory=peak,
                             free=mt.memory(self.tr, self.machine.available_mb))
            elif state == job.CANCELLED:
                self._finish("cancelled")
            else:
                self._finish("failed", getattr(job, "log_tail", lambda: "")())
            return
        if self.stage == "mesh":
            self._start_solve()
        elif self.stage == "solve":
            self._solved(job)
        elif self.stage == "trial":
            self._tried(job)

    def _solved(self, job):
        t = self.tr.t
        self.status.setText(t("mo.reading"))
        QApplication.processEvents()
        info = optimizer.error_by_element(self.analysis, self.mesh, self.singular,
                                          self.stress_excluded)
        sample = SolverSample(info["nodes"], job.seconds, job.peak_mb)
        self.samples.append(sample)
        machine_calibration.save(self.machine, [sample])  # real solves teach the computer
        self.passes.append(ad.Pass(info["nodes"], info["error_regular"], info["max_stress"],
                                   info["max_stress_regular"], info["max_displacement"],
                                   time.monotonic() - self.pass_started, job.peak_mb,
                                   global_error=info["error"]))
        self._add_row(self.passes[-1])
        self._show_forecast()
        self.doc.openTransaction("PartReview: optimise mesh")  # undoable, like the regions
        optimizer.save_history(self.mesh, self.passes)
        self.doc.commitTransaction()
        target = self.target_box.currentData()
        reason = ad.stop_reason(self.passes, target)
        if reason:
            return self._finish(reason)
        ratios = ad.element_ratios(info["error_sq"], info["energy_sq"], target)
        current = dict(mesh_runner.region_sizes(self.mesh))
        global_size = self.mesh.CharacteristicLengthMax.getValueAs("mm").Value
        for faces in info["faces"]:
            for face in faces:
                current.setdefault(face, global_size)
        # supports and singular regions are not refined: there the error does not converge
        refined = ad.face_sizes(info["faces"], info["sizes"], ratios, current,
                                self.singular | self.stress_excluded)
        if not refined:
            return self._finish("nothing")
        merged = dict(mesh_runner.region_sizes(self.mesh))
        merged.update(refined)
        self.pending_groups = ad.group_by_size(merged)
        if self.trial is None:
            self.trial = mesh_runner.TrialDocument(self.solid.Shape.copy())
        self._start_job("trial", self.trial.job_like(
            self.mesh, self.pending_groups, GMSH_TIME_LIMIT_S,
            GMSH_MEMORY_SHARE * self.machine.available_mb))

    def _tried(self, job):
        """The refined mesh was generated in the hidden document: does it fit?"""
        nodes = job.run.nodes
        self.machine = machine_profile()
        model = mp.part_model(self.samples, mp.machine_time_law(self.history_samples)
                              if self.history_samples else None)
        # A failed pass costs nothing here (old results stay until the new solve
        # succeeds; the watchdog stops CalculiX at 80 % of free memory), so the plan
        # uses the probes' planning margin and the 'tight' limit.
        margin = 1 + min(model.error, mp.PROBE_PLANNING_ERROR)
        if model.memory_mb(nodes) * margin > TIGHT_FRACTION * self.machine.available_mb:
            return self._finish("memory", nodes=nodes)
        speed = speed_factor(self.samples or self.history_samples)
        predicted = mp.total_seconds(model, nodes, None, speed) + job.elapsed
        if time.monotonic() - self.started + predicted > self.time_box.currentData():
            return self._finish("time", nodes=nodes)
        self.doc.openTransaction("PartReview: optimise mesh")  # undoable
        mesh_runner.set_regions(self.doc, self.mesh, self.solid, self.pending_groups)
        self.doc.recompute()
        self.doc.commitTransaction()
        self._start_job("mesh", mesh_runner.GmshJob(
            self.mesh, GMSH_TIME_LIMIT_S, GMSH_MEMORY_SHARE * self.machine.available_mb,
            load_into_object=True))

    def _finish(self, reason, detail="", nodes=0, memory="", free=""):
        t = self.tr.t
        self._set_busy(False)
        self.stop_key = reason
        last = self.passes[-1] if self.passes else None
        text = t("mo.stop." + reason, target=int(round(100 * self.target_box.currentData())),
                 nodes=self.tr.integer(nodes), memory=memory, free=free)
        if last is not None:
            text += " " + t("mo.final", error=self.tr.number(100 * last.error, 3),
                            nodes=self.tr.integer(last.nodes),
                            elapsed=format_duration(time.monotonic() - self.started))
        if detail:
            text += "\n" + detail[-600:]
        self.status.setText(text)
        App.Console.PrintMessage("PartReview: %s\n" % text.split("\n")[0])

    # --- view -------------------------------------------------------------------------

    def _add_row(self, p):
        row = self.table.rowCount()
        self.table.insertRow(row)
        cells = [str(row), self.tr.integer(p.nodes), self.tr.number(100 * p.error, 3) + " %",
                 self.tr.number(100 * p.global_error, 3) + " %",
                 "%s MPa" % self.tr.number(p.max_stress_regular, 3),
                 "%s mm" % self.tr.number(p.max_displacement, 4), format_duration(p.seconds),
                 mt.memory(self.tr, p.peak_mb)]
        for col, value in enumerate(cells):
            self.table.setItem(row, col, QTableWidgetItem(value))

    def _show_forecast(self):
        """Which targets fit THIS computer, from the last solve: nodes needed by the
        a priori convergence rate (adaptive.nodes_for_error), memory and time from
        the solves measured on this part."""
        t, last = self.tr.t, self.passes[-1]
        model = mp.part_model(self.samples, mp.machine_time_law(self.history_samples)
                              if self.history_samples else None)
        free = machine_profile().available_mb
        margin = 1 + min(model.error, mp.PROBE_PLANNING_ERROR)
        speed = speed_factor(self.samples or self.history_samples)
        lines = []
        for target in TARGETS:
            pct = int(round(100 * target))
            if last.error <= target:
                lines.append(t("mo.fc.reached", target=pct))
                continue
            nodes = ad.nodes_for_error(last.nodes, last.error, target)
            memory = model.memory_mb(nodes) * margin
            seconds = mp.total_seconds(model, nodes, None, speed) if model.time_known else None
            key = "mo.fc.fits" if memory <= TIGHT_FRACTION * free else "mo.fc.too_big"
            lines.append(t(key, target=pct, nodes=self.tr.integer(nodes),
                           memory=mt.memory(self.tr, memory), free=mt.memory(self.tr, free),
                           time=format_duration(seconds) if seconds is not None
                           else t("ma.time_unknown")))
        self.forecast.setText("\n".join(lines) + "\n" + t("mo.fc.note"))

    def _show_progress(self):
        t = self.tr.t
        what = t("mo.stage." + self.stage, n=len(self.passes))
        elapsed = time.monotonic() - self.started
        self.status.setText(t("mo.progress", what=what, elapsed=format_duration(elapsed),
                              limit=format_duration(self.time_box.currentData())))

    def _set_busy(self, busy):
        self.progress.setVisible(busy)
        self.cancel_button.setVisible(busy)
        self.start_button.setEnabled(not busy and self.mesh is not None)
        self.target_box.setEnabled(not busy)
        self.time_box.setEnabled(not busy)
        if self.mesh_combo is not None:
            self.mesh_combo.setEnabled(not busy)

    def _cleanup(self):
        if self.job is not None:
            self.job.cancel()
            self.job = None
        self.timer.stop()
        if self.trial is not None:
            self.trial.close()
            self.trial = None
