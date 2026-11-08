# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Mesh assistant task panel (v1.5.0, decision 007). Thin: rules live in domain/.

Flow: Analyse part -> Try the options (hidden document, real Gmsh runs, budget)
-> Create mesh (new Gmsh object in the user's document, undoable). Gmsh runs as a
separate process polled by a timer, so the GUI never freezes (rules 8 and 11).
"""

import FreeCAD as App  # type: ignore
import FreeCADGui as Gui  # type: ignore
from PySide6.QtCore import Qt, QTimer  # type: ignore
from PySide6.QtGui import QColor  # type: ignore
from PySide6.QtWidgets import (  # type: ignore
    QAbstractItemView,
    QApplication,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..adapters import geometry_reader, mesh_runner
from ..adapters.machine import machine_profile
from ..domain import mesh_texts as mt
from ..domain.geometry_summary import find_issues
from ..domain.i18n import Translator
from ..domain.mesh_budget import BudgetStatus, check_budget, solver_memory_mb
from ..domain.mesh_sizing import mesh_options, with_straight_edges
from .report_dialog import ui_language

GMSH_TIME_LIMIT_S = 300  # one Gmsh run; the spike's finest useful mesh took 13 s
GMSH_MEMORY_SHARE = 0.7  # Gmsh may use up to 70 % of the memory free when it starts
STATUS_COLORS = {BudgetStatus.FITS: QColor(46, 125, 50), BudgetStatus.TIGHT: QColor(178, 106, 0),
                 BudgetStatus.TOO_BIG: QColor(198, 40, 40)}
COLUMNS = ("ma.col.option", "ma.col.size", "ma.col.nodes", "ma.col.memory", "ma.col.status",
           "ma.col.gmsh")


class _Result:
    """What one Gmsh run measured for one option."""

    def __init__(self, option, job, check):
        self.option, self.job, self.check = option, job, check


class MeshAssistantPanel:
    def __init__(self, doc):
        self.doc = doc
        self.tr = Translator(ui_language())
        t = self.tr.t
        self.solid = None
        self.summary = None
        self.options = []
        self.results = {}  # MeshLevel -> _Result (or None when skipped/failed)
        self.queue = []
        self.job = None
        self.job_kind = ""
        self.job_option = None
        self.trial = None
        self.machine = machine_profile()

        self.form = QWidget()
        self.form.setWindowTitle(t("ma.title"))
        layout = QVBoxLayout(self.form)

        intro = QLabel(t("ma.intro"))
        intro.setWordWrap(True)
        self.analyze_button = QPushButton(t("ma.analyze"))
        self.analyze_button.clicked.connect(self.analyze)
        layout.addWidget(intro)
        layout.addWidget(self.analyze_button)

        self.part_box = QGroupBox(t("ma.group.part"))
        self.part_form = QFormLayout(self.part_box)
        layout.addWidget(self.part_box)

        self.issues_box = QGroupBox(t("ma.group.issues"))
        issues_layout = QVBoxLayout(self.issues_box)
        self.issues = QListWidget()
        self.issues.setWordWrap(True)
        self.issues.setToolTip(t("ma.issue_tip"))
        self.issues.itemDoubleClicked.connect(self._select_issue)
        issues_layout.addWidget(self.issues)
        layout.addWidget(self.issues_box)

        self.machine_box = QGroupBox(t("ma.group.machine"))
        machine_layout = QVBoxLayout(self.machine_box)
        self.machine_label = QLabel()
        self.machine_label.setWordWrap(True)
        machine_layout.addWidget(self.machine_label)
        layout.addWidget(self.machine_box)

        self.options_box = QGroupBox(t("ma.group.options"))
        options_layout = QVBoxLayout(self.options_box)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([t(c) for c in COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._show_selected)
        self.reason_label = QLabel()
        self.reason_label.setWordWrap(True)
        row = QHBoxLayout()
        self.test_button = QPushButton(t("ma.test"))
        self.test_button.setToolTip(t("ma.test_tip"))
        self.test_button.clicked.connect(self.test_options)
        self.best_button = QPushButton(t("ma.best"))
        self.best_button.clicked.connect(self.pick_best)
        row.addWidget(self.test_button)
        row.addWidget(self.best_button)
        options_layout.addWidget(self.table)
        options_layout.addWidget(self.reason_label)
        options_layout.addLayout(row)
        layout.addWidget(self.options_box)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # busy indicator: Gmsh does not report a percentage
        self.cancel_button = QPushButton(t("ma.cancel"))
        self.cancel_button.clicked.connect(self.cancel)
        progress_row = QHBoxLayout()
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.cancel_button)
        layout.addWidget(self.status_label)
        layout.addLayout(progress_row)

        actions = QHBoxLayout()
        self.create_button = QPushButton(t("ma.create"))
        self.create_button.setToolTip(t("ma.create_tip"))
        self.create_button.clicked.connect(self.create_mesh)
        self.remove_button = QPushButton(t("ma.remove"))
        self.remove_button.clicked.connect(self.remove_meshes)
        actions.addWidget(self.create_button)
        actions.addWidget(self.remove_button)
        layout.addLayout(actions)

        self.details_box = QGroupBox(t("ma.group.details"))
        self.details_box.setCheckable(True)
        self.details_box.setChecked(False)
        details_layout = QVBoxLayout(self.details_box)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setVisible(False)
        self.details_box.toggled.connect(self.details.setVisible)
        details_layout.addWidget(self.details)
        layout.addWidget(self.details_box)
        layout.addStretch(1)

        self.timer = QTimer()
        self.timer.setInterval(150)
        self.timer.timeout.connect(self._tick)
        self._show_machine()
        self._set_busy(False)
        self._enable(False)
        self._preselect()

    # --- FreeCAD task panel protocol ---------------------------------------------

    def getStandardButtons(self):
        return QDialogButtonBox.StandardButton.Close

    def reject(self):
        self._cleanup()
        Gui.Control.closeDialog()
        return True

    def accept(self):
        return self.reject()

    # --- steps --------------------------------------------------------------------

    def _preselect(self):
        """Analyse right away when a solid is already selected."""
        if any(geometry_reader.is_meshable(o) for o in Gui.Selection.getSelection(self.doc.Name)):
            self.analyze()

    def analyze(self):
        t = self.tr.t
        solids = [o for o in Gui.Selection.getSelection(self.doc.Name)
                  if geometry_reader.is_meshable(o)]
        if not solids:
            self.status_label.setText(t("ma.no_solid"))
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.solid = solids[0]
            self.summary = geometry_reader.summarize(self.solid)
        finally:
            QApplication.restoreOverrideCursor()
        self._close_trial()
        self.results = {}
        self.options = mesh_options(self.summary)
        self.part_box.setTitle("%s: %s" % (t("ma.group.part"), self.summary.label))
        while self.part_form.rowCount():
            self.part_form.removeRow(0)
        for label, value, tip in mt.part_rows(self.summary, self.tr):
            value_label = QLabel(value)
            value_label.setToolTip(tip)
            self.part_form.addRow(label, value_label)
        self.issues.clear()
        issues = find_issues(self.summary)
        for issue in issues:
            item = QListWidgetItem("⚠ " + mt.issue_text(issue, self.summary, self.tr))
            item.setData(Qt.UserRole, issue.elements)
            self.issues.addItem(item)
        if not issues:
            self.issues.addItem(QListWidgetItem("✔ " + t("ma.no_issues")))
        self.machine = machine_profile()
        self._show_machine()
        self._fill_table()
        self.table.selectRow(0)  # coarse is the default recommendation (owner's choice)
        self.status_label.setText("")
        self._enable(True)

    def test_options(self):
        if self.summary is None or self.job is not None:
            return
        self.machine = machine_profile()
        self._show_machine()
        if self.trial is None:
            self.trial = mesh_runner.TrialDocument(geometry_reader.solid_shape(self.solid))
        self.results = {}
        self._fill_table()
        self.queue = list(self.options)
        self._next_trial()

    def pick_best(self):
        """Finest tried option that fits with margin (never one with inverted elements)."""
        best = None
        for row, option in enumerate(self.options):
            result = self.results.get(option.level)
            if result and result.check.status is BudgetStatus.FITS and not result.job.run.inverted:
                best = row
        if best is None:
            self.status_label.setText(self.tr.t("ma.best_none"))
            return
        self.table.selectRow(best)

    def create_mesh(self):
        t = self.tr.t
        option = self._selected_option()
        if option is None or self.job is not None:
            return
        result = self.results.get(option.level)
        if result is not None:
            option = result.option  # keeps the straight-edge fix found in the trial
            if result.check.status is BudgetStatus.TOO_BIG:
                answer = QMessageBox.question(self.form, t("ma.title"), t("ma.confirm_too_big"))
                if answer != QMessageBox.Yes:
                    return
        mesh = mesh_runner.create_mesh_object(self.doc, self.solid, option, __version__)
        self._start(mesh_runner.GmshJob(mesh, GMSH_TIME_LIMIT_S, self._gmsh_memory_limit(),
                                        load_into_object=True), "create", option)

    def remove_meshes(self):
        t = self.tr.t
        count = mesh_runner.remove_assistant_objects(self.doc)
        self.status_label.setText(t("ma.removed", count=count) if count
                                  else t("ma.none_to_remove"))

    def cancel(self):
        if self.job is not None:
            self.job.cancel()

    # --- Gmsh jobs ------------------------------------------------------------------

    def _gmsh_memory_limit(self):
        return GMSH_MEMORY_SHARE * self.machine.available_mb

    def _next_trial(self):
        if not self.queue:
            self.status_label.setText(self.tr.t("ma.tested"))
            return
        option = self.queue.pop(0)
        self._start(self.trial.job(option, GMSH_TIME_LIMIT_S, self._gmsh_memory_limit()),
                    "trial", option)

    def _start(self, job, kind, option):
        self.job, self.job_kind, self.job_option = job, kind, option
        job.start()
        self._set_busy(True)
        self.timer.start()

    def _tick(self):
        t = self.tr.t
        job = self.job
        if job is None:
            self.timer.stop()
            return
        state = job.poll()
        level = t("ma.level." + self.job_option.level.value).lower()
        if state == job.RUNNING:
            self.status_label.setText(t("ma.running", level=level, seconds=int(job.elapsed)))
            return
        self.timer.stop()
        self.job = None
        self._set_busy(False)
        self.details.setPlainText("%s\n\n%s" % (mt.gmsh_settings(self.job_option, self.tr),
                                                job.log_tail()))
        if state != job.DONE:
            self.queue = []
            self.status_label.setText(
                t("ma.cancelled") if state == job.CANCELLED else
                t("ma.failed", level=level, reason=t("ma.reason." + state)))
            return
        if self.job_kind == "trial" and job.run.inverted and not self.job_option.straight_edges:
            self.queue.insert(0, with_straight_edges(self.job_option))  # automatic fix
            self._next_trial()
            return
        check = check_budget(job.run.nodes, self.machine)
        if self.job_kind == "trial":
            self.results[self.job_option.level] = _Result(self.job_option, job, check)
            self._fill_table()
            if check.status is BudgetStatus.TOO_BIG:
                self.queue = []  # finer options would only be bigger
                self._fill_table()
            self._next_trial()
            return
        self._created(job, check)

    def _created(self, job, check):
        t = self.tr.t
        mesh = job.mesh_obj
        inside = [a for a in mesh_runner.analyses(self.doc) if mesh in a.Group]
        busy = [a for a in mesh_runner.analyses(self.doc) if a not in inside
                and mesh_runner.analysis_meshes(a)]
        if inside:
            where = t("ma.created_in_analysis", analysis=inside[0].Label)
        elif len(busy) == 1:
            where = t("ma.created_beside", analysis=busy[0].Label,
                      old=mesh_runner.analysis_meshes(busy[0])[0].Label)
        else:
            where = t("ma.created_at_root")
        self.status_label.setText("%s %s" % (
            t("ma.created", label=mesh.Label, nodes=self.tr.integer(job.run.nodes),
              status=mt.status_text(check, self.tr)), where))

    # --- view helpers ---------------------------------------------------------------

    def _fill_table(self):
        t = self.tr.t
        self.table.setRowCount(len(self.options))
        tried = set(self.results)
        stopped = any(r.check.status is BudgetStatus.TOO_BIG for r in self.results.values())
        for row, option in enumerate(self.options):
            result = self.results.get(option.level)
            cells = [t("ma.level." + option.level.value), mt.mm(self.tr, option.max_size)]
            color = None
            if result is not None:
                nodes = result.job.run.nodes
                status = mt.status_text(result.check, self.tr)
                if result.option.straight_edges:
                    status += t("ma.status.fixed")
                cells += [self.tr.integer(nodes), "~" + mt.memory(self.tr, solver_memory_mb(nodes)),
                          status, "%s s · %s" % (self.tr.number(result.job.elapsed, 2),
                                                 mt.memory(self.tr, result.job.peak_mb))]
                color = STATUS_COLORS[result.check.status]
            else:
                skipped = stopped and option.level not in tried
                cells += [mt.nodes_estimate(option, self.tr), "", t("ma.status.skipped") if skipped
                          else t("ma.status.not_tested"), ""]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(mt.option_reason(option, self.summary, self.tr))
                if color is not None and col == 4:
                    item.setForeground(color)
                self.table.setItem(row, col, item)

    def _selected_option(self):
        rows = {i.row() for i in self.table.selectedItems()}
        return self.options[min(rows)] if rows else None

    def _show_selected(self):
        option = self._selected_option()
        if option is None:
            return
        result = self.results.get(option.level)
        shown = result.option if result is not None else option
        self.reason_label.setText(mt.option_reason(option, self.summary, self.tr))
        self.details.setPlainText(mt.gmsh_settings(shown, self.tr))

    def _show_machine(self):
        self.machine_label.setText(mt.machine_text(self.machine, self.tr))

    def _select_issue(self, item):
        elements = item.data(Qt.UserRole)
        if not elements or self.solid is None:
            return
        Gui.Selection.clearSelection()
        for element in elements:
            Gui.Selection.addSelection(self.doc.Name, self.solid.Name, element)

    def _set_busy(self, busy):
        self.progress.setVisible(busy)
        self.cancel_button.setVisible(busy)
        for widget in (self.analyze_button, self.test_button, self.best_button,
                       self.create_button, self.remove_button):
            widget.setEnabled(not busy and (widget is self.analyze_button
                                            or widget is self.remove_button
                                            or self.summary is not None))

    def _enable(self, analysed):
        for widget in (self.part_box, self.issues_box, self.options_box, self.details_box):
            widget.setVisible(analysed)
        self._set_busy(False)

    def _close_trial(self):
        if self.trial is not None:
            self.trial.close()
            self.trial = None

    def _cleanup(self):
        if self.job is not None:
            self.job.cancel()
            self.job = None
        self.timer.stop()
        self._close_trial()
