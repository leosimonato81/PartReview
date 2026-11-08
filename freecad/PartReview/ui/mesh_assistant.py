# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Mesh assistant task panel (v1.5.0, decision 007). Thin: rules live in domain/.

Flow: Analyse part -> Try the options (hidden document: real Gmsh runs for 5 sizes,
then CalculiX trials on the smaller meshes of THIS part on THIS computer) ->
optional objective (fits in memory / solves within 1, 5 or 10 minutes) ->
Create mesh (new Gmsh object in the user's document, undoable).
Every external program runs as a separate, watched process polled by a timer, so
the GUI never freezes (CLAUDE.md rules 8 and 11).
"""

import time
from dataclasses import replace

import FreeCAD as App  # type: ignore
import FreeCADGui as Gui  # type: ignore
from PySide6.QtCore import QPointF, QSize, Qt, QTimer  # type: ignore
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF  # type: ignore
from PySide6.QtWidgets import (  # type: ignore
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QGridLayout,
    QSizePolicy,
    QStyle,
    QToolButton,
    QComboBox,
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
from ..adapters import fem_reader, geometry_reader, mesh_runner
from ..adapters import machine_calibration
from ..adapters.machine import machine_profile
from ..domain import mesh_plan as mp
from ..domain import mesh_texts as mt
from ..domain.geometry_summary import find_issues
from ..domain.i18n import Translator
from ..domain.mesh_budget import FITS_FRACTION, TIGHT_FRACTION, BudgetStatus
from ..domain.mesh_sizing import (DEFAULT_LEVEL, MeshLevel, auto_option, estimate_nodes,
                                  mesh_options, with_straight_edges)
from ..domain.solver_model import SolverSample, format_duration, speed_factor
from .report_dialog import ui_language

GMSH_TIME_LIMIT_S = 300  # one Gmsh run (the spike's 200 000-node mesh took 13 s)
GMSH_MEMORY_SHARE = 0.7  # a Gmsh run may use up to 70 % of the free memory
PROBE_TIME_LIMIT_S = 180  # one CalculiX trial is planned below 60 s; hard stop at 180 s
PROBE_MEMORY_SHARE = 0.65  # hard stop for a CalculiX trial
MAX_PROBES = 3
# Meshed first; finer sizes are meshed only if the law measured on this part says
# they may fit (each fine Gmsh trial costs 15-30 s on a typical part).
CHEAP_LEVELS = (MeshLevel.VERY_COARSE, MeshLevel.COARSE, MeshLevel.MEDIUM)
REFINE_MAX_AREA_SHARE = 0.05  # refine support/load faces only when small (<= 5 % of the area)
AUTO_ATTEMPTS = 3  # size search for an objective (CLAUDE.md rule 6)
GMSH_S_PER_NODE = 7e-5  # spike 8.0: 13.3 s for 198 000 nodes; replaced by measurements
STATUS_COLORS = {BudgetStatus.FITS: QColor(46, 125, 50), BudgetStatus.TIGHT: QColor(178, 106, 0),
                 BudgetStatus.TOO_BIG: QColor(198, 40, 40)}
COLUMNS = ("ma.col.option", "ma.col.size", "ma.col.nodes", "ma.col.memory", "ma.col.time",
           "ma.col.status", "ma.col.gmsh")


# Same card look as the report dialog's level cards (any FreeCAD theme).
CARD_STYLE = ("QToolButton{border:1px solid palette(mid);border-radius:6px;padding:6px}"
              "QToolButton:checked{border:3px solid palette(highlight);"
              "background:palette(highlight);color:palette(highlighted-text)}")  # no bold: fits
DENSITY = {MeshLevel.VERY_COARSE: 1, MeshLevel.COARSE: 2, MeshLevel.MEDIUM: 3,
           MeshLevel.FINE: 4, MeshLevel.VERY_FINE: 5, MeshLevel.AUTO: 3}


def mesh_icon(divisions, size=48):
    """A triangle split into divisions^2 smaller ones: a picture of mesh density."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    a, b, c = QPointF(4, size - 6), QPointF(size - 4, size - 6), QPointF(size / 2, 5)
    p.setBrush(QColor(232, 238, 246))
    p.setPen(QPen(QColor(44, 62, 80), 2))
    p.drawPolygon(QPolygonF([a, b, c]))
    p.setPen(QPen(QColor(44, 62, 80), 1))
    n = max(1, divisions)
    for i in range(1, n):
        f = i / n
        p.drawLine(a + (c - a) * f, b + (c - b) * f)  # parallel to the base
        p.drawLine(a + (b - a) * f, a + (b - a) * f + (c - a) * (1 - f))  # parallel to a-c
        p.drawLine(b + (a - b) * f, b + (a - b) * f + (c - b) * (1 - f))  # parallel to b-c
    p.end()
    return QIcon(pixmap)


# Button hierarchy: one primary action per step (theme highlight color), the
# rest secondary. Icons come from the platform style, so they follow the theme.
PRIMARY_STYLE = ("QPushButton{font-weight:bold;padding:6px 14px;border-radius:4px;"
                 "background:palette(highlight);color:palette(highlighted-text);}"
                 "QPushButton:disabled{background:palette(button);color:palette(mid);}")


def _button(text, icon, slot, primary=False, tip=""):
    button = QPushButton(QApplication.style().standardIcon(icon), text)
    button.clicked.connect(slot)
    button.setMinimumHeight(34 if primary else 28)
    button.setIconSize(QSize(18, 18) if primary else QSize(16, 16))
    if primary:
        button.setStyleSheet(PRIMARY_STYLE)
    if tip:
        button.setToolTip(tip)
    return button


class _Trial:
    """A Gmsh run for one option (and, maybe, a CalculiX trial on it)."""

    def __init__(self, option, job, fixed=False):
        self.option, self.job = option, job
        self.fixed = fixed  # straight edges were needed to remove inverted elements
        self.sample = None  # SolverSample when CalculiX was measured on this mesh

    @property
    def nodes(self):
        return self.job.run.nodes


class MeshAssistantPanel:
    def __init__(self, doc):
        self.doc = doc
        self.tr = Translator(ui_language())
        t = self.tr.t
        self.solid = None
        self.summary = None
        self.options = []  # MeshOption shown in the table (5 levels + automatic)
        self.trials = {}  # MeshLevel -> _Trial
        self.skipped = set()  # levels not tried because they would be too big
        self.tasks = []  # pending work: ("gmsh", option) / ("probe", level) / ...
        self.task = None  # current (kind, payload)
        self.job = None
        self.trial_doc = None
        self.machine = machine_profile()
        self.machine_samples, self.machine_date = machine_calibration.load(self.machine)
        self.model = self._prior()
        self.run_started = 0.0
        self.steps_done = 0
        self.steps_total = 0
        self.objective = None
        self.auto_attempt = 0
        self.auto_target = 0
        self.probes_pending = False
        self.finer_pending = []
        self.predicted = {}
        self.probe_samples = []  # CalculiX trials of this part on this computer
        self.fixing = False
        self.refine = ()  # faces refined locally: supports, loads, small radii
        self.recommended = None  # (MeshLevel, reason key) after a test
        self.test_run = False

        self.form = QWidget()
        self.form.setWindowTitle(t("ma.title"))
        layout = QVBoxLayout(self.form)

        # Step 1: the part is chosen from a list of the document's solids (obvious),
        # or taken from the 3D selection; changing it analyses it at once.
        self.part_box = QGroupBox(t("ma.group.part"))
        part_layout = QVBoxLayout(self.part_box)
        pick_label = QLabel("<b>%s</b>" % t("ma.pick"))
        self.part_combo = QComboBox()
        self.part_combo.setMinimumHeight(32)
        self.part_combo.setToolTip(t("ma.pick_tip"))
        self.analyze_button = _button(t("ma.use_selection"), QStyle.SP_ArrowDown,
                                      self.use_selection, tip=t("ma.use_selection_tip"))
        pick_row = QHBoxLayout()
        pick_row.addWidget(self.part_combo, 1)
        pick_row.addWidget(self.analyze_button)
        self.part_form = QFormLayout()
        part_layout.addWidget(pick_label)
        part_layout.addLayout(pick_row)
        part_layout.addLayout(self.part_form)
        layout.addWidget(self.part_box)

        self.issues_box = QGroupBox(t("ma.group.issues"))
        issues_layout = QVBoxLayout(self.issues_box)
        self.issues = QListWidget()
        self.issues.setWordWrap(True)
        self.issues.setToolTip(t("ma.issue_tip"))
        self.issues.itemDoubleClicked.connect(self._select_issue)
        self.issues.setMaximumHeight(120)  # compact: scroll for long lists
        issues_layout.addWidget(self.issues)
        layout.addWidget(self.issues_box)

        self.machine_box = QGroupBox(t("ma.group.machine"))
        machine_layout = QFormLayout(self.machine_box)  # one row per source of information
        self.machine_rows = []
        for _ in range(3):
            value = QLabel()
            value.setWordWrap(True)
            title = QLabel()
            bold = title.font()
            bold.setBold(True)
            title.setFont(bold)
            machine_layout.addRow(title, value)
            self.machine_rows.append((title, value))
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
        self.test_button = _button(t("ma.test"), QStyle.SP_MediaPlay, self.test_options,
                                   primary=True, tip=t("ma.test_tip"))
        self.objective_box = QComboBox()
        for objective in mp.Objective:
            self.objective_box.addItem(t("ma.objective." + objective.value), objective)
        self.auto_button = _button(t("ma.auto"), QStyle.SP_ArrowForward, self.auto_mesh,
                                   tip=t("ma.auto_tip"))
        auto_box = QGroupBox(t("ma.group.auto"))
        objective_row = QHBoxLayout(auto_box)
        objective_row.addWidget(self.objective_box, 1)
        objective_row.addWidget(self.auto_button)
        self.recommend_label = QLabel()
        self.recommend_label.setWordWrap(True)
        self.recommend_label.setTextFormat(Qt.RichText)
        self.recommend_label.setStyleSheet(
            "QLabel{border:1px solid palette(mid);border-radius:6px;padding:8px;}")
        self.refine_label = QLabel()
        self.refine_label.setWordWrap(True)
        self.cards_widget = QWidget()
        self.cards_layout = QGridLayout(self.cards_widget)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_widget.setStyleSheet(CARD_STYLE)
        self.card_group = QButtonGroup(self.form)
        self.card_group.setExclusive(True)
        self.cards = {}
        self.current_label = QLabel()  # the mesh the analysis already has, if any
        self.current_label.setWordWrap(True)
        self.current_label.setTextFormat(Qt.RichText)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.progress = QProgressBar()
        self.cancel_button = _button(t("ma.cancel"), QStyle.SP_DialogCancelButton, self.cancel)
        progress_row = QHBoxLayout()
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.cancel_button)
        options_layout.addWidget(self.recommend_label)
        options_layout.addWidget(self.current_label)
        options_layout.addWidget(self.cards_widget)
        options_layout.addWidget(self.test_button)
        options_layout.addWidget(self.status_label)
        options_layout.addLayout(progress_row)
        options_layout.addWidget(auto_box)
        layout.addWidget(self.options_box)

        self.create_title = QLabel("<b>%s</b>" % t("ma.group.create"))
        layout.addWidget(self.create_title)
        actions = QHBoxLayout()
        self.create_button = _button(t("ma.create"), QStyle.SP_DialogApplyButton,
                                     self.create_mesh, primary=True, tip=t("ma.create_tip"))
        actions.addWidget(self.create_button)
        layout.addLayout(actions)

        self.details_box = QGroupBox(t("ma.group.details"))
        self.details_box.setCheckable(True)
        self.details_box.setChecked(False)
        self.details_box.setFlat(True)
        details_layout = QVBoxLayout(self.details_box)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        details_inner = QWidget()  # numbers table, refinement note, Gmsh settings and log
        inner = QVBoxLayout(details_inner)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.addWidget(self.table)
        inner.addWidget(self.refine_label)
        inner.addWidget(self.details)
        self.table.setVisible(True)
        details_inner.setVisible(False)
        self.details_box.toggled.connect(details_inner.setVisible)
        details_layout.addWidget(details_inner)
        layout.addWidget(self.details_box)
        layout.addStretch(1)

        self.timer = QTimer()
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._tick)
        self._show_machine()
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

    # --- user actions ---------------------------------------------------------------

    def _preselect(self):
        """Fill the part list; pick the 3D selection, or the only solid, and analyse."""
        t = self.tr.t
        self.part_combo.blockSignals(True)
        self.part_combo.clear()
        self.part_combo.addItem(t("ma.pick_placeholder"), None)
        for obj in geometry_reader.document_solids(self.doc):
            bb = obj.Shape.BoundBox
            self.part_combo.addItem("%s  (%s × %s × %s mm)" % (
                obj.Label, self.tr.number(bb.XLength, 3), self.tr.number(bb.YLength, 3),
                self.tr.number(bb.ZLength, 3)), obj.Name)
        self.part_combo.blockSignals(False)
        self.part_combo.currentIndexChanged.connect(self._part_chosen)
        selected = [o for o in Gui.Selection.getSelection(self.doc.Name)
                    if geometry_reader.is_meshable(o)]
        if selected:
            self._choose(selected[0])
        elif self.part_combo.count() == 2:  # one solid in the document
            self.part_combo.setCurrentIndex(1)
        elif self.part_combo.count() == 1:
            self.status_label.setText(t("ma.no_solid"))

    def _choose(self, obj):
        index = self.part_combo.findData(obj.Name)
        if index < 0:  # not a final solid (e.g. an intermediate feature): add it
            self.part_combo.addItem(obj.Label, obj.Name)
            index = self.part_combo.count() - 1
        if index == self.part_combo.currentIndex():
            self.analyze()
        else:
            self.part_combo.setCurrentIndex(index)  # -> _part_chosen -> analyze

    def _part_chosen(self, *_):
        if self.part_combo.currentData():
            self.analyze()

    def use_selection(self):
        selected = [o for o in Gui.Selection.getSelection(self.doc.Name)
                    if geometry_reader.is_meshable(o)]
        if not selected:
            self.status_label.setText(self.tr.t("ma.no_solid"))
            return
        self._choose(selected[0])

    def analyze(self):
        t = self.tr.t
        name = self.part_combo.currentData()
        obj = self.doc.getObject(name) if name else None
        if obj is None or self.job is not None:
            self.status_label.setText(t("ma.no_solid"))
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.solid = obj
            self.summary = geometry_reader.summarize(self.solid)
        finally:
            QApplication.restoreOverrideCursor()
        self._close_trial_doc()
        self.trials, self.skipped = {}, set()
        self.model = self._prior()
        self.probe_samples = []
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
        targets = mesh_runner.constraint_targets(self.doc, self.solid)
        for label, kind, subs in targets:
            if any(s.startswith(("Edge", "Vertex")) for s in subs):
                item = QListWidgetItem("⚠ " + t("ma.issue.line_constraint", label=label,
                                                 where=", ".join(subs[:4])))
                item.setData(Qt.UserRole, subs)
                self.issues.addItem(item)
                issues.append(None)
        small = []  # small radii: curvature-based sizing already refines them
        shape = geometry_reader.solid_shape(self.solid)
        faces = [s for _, _, subs in targets for s in subs if s.startswith("Face")
                 and shape.getElement(s).Area <= REFINE_MAX_AREA_SHARE * self.summary.area]
        self.refine = tuple(dict.fromkeys(faces + small))
        self.refine_label.setText(t("ma.refine", count=len(self.refine)) if self.refine
                                  else t("ma.refine_none"))
        count = sum(1 for i in range(self.issues.count()))
        self.issues_box.setTitle("%s (%d)" % (t("ma.group.issues"), count))
        if not issues:
            self.issues.addItem(QListWidgetItem("✔ " + t("ma.no_issues")))
        self.machine = machine_profile()
        self._show_machine()
        mine = [m for m in fem_reader.solver_meshes(self.doc)
                if getattr(getattr(m, "Shape", None), "Name", None) == self.solid.Name]
        grouped = {o.Name for a in mesh_runner.analyses(self.doc) for o in a.Group}
        in_analysis = [m for m in mine if m.Name in grouped]
        self.current_mesh = (in_analysis or mine or [None])[0]
        self.recommended = None
        for button in self.cards.values():
            self.card_group.removeButton(button)
            button.deleteLater()
        self.cards = {}
        self._fill_table()
        self._select_level(DEFAULT_LEVEL)  # medium: ~2 elements across the wall
        self.recommend_label.setText(t("ma.recommend.before"))
        self.status_label.setText("")
        self._enable(True)

    def test_options(self):
        if self.summary is None or self.job is not None:
            return
        self.machine = machine_profile()
        if self.trial_doc is None:
            self.trial_doc = mesh_runner.TrialDocument(geometry_reader.solid_shape(self.solid))
        self.trials, self.skipped = {}, set()
        self.model = self._prior()
        self.probe_samples = []
        self.options = [o for o in self.options if o.level is not MeshLevel.AUTO]
        self.recommended = None
        self.test_run = True
        self.predicted = {}
        self._fill_table()
        cheap = [o for o in self.options if o.level in CHEAP_LEVELS]
        self.finer_pending = [o for o in self.options if o.level not in CHEAP_LEVELS]
        self._run([("gmsh", o) for o in cheap])

    def auto_mesh(self):
        t = self.tr.t
        if self.job is not None or self.summary is None:
            return
        if not self.trials:
            self.status_label.setText(t("ma.need_test"))
            return
        self.machine = machine_profile()
        self.objective = self.objective_box.currentData()
        if mp.OBJECTIVE_SECONDS[self.objective] is not None and not self.model.time_known:
            self.status_label.setText(t("ma.need_time"))
            return
        self.auto_target = mp.target_nodes(self.model, self.machine.available_mb,
                                           self.objective, FITS_FRACTION)
        smallest = min(tr.nodes for tr in self.trials.values())
        if self.auto_target < smallest:
            self.status_label.setText(t("ma.auto_none", objective=self.objective_box.currentText()))
            self._select_level(MeshLevel.VERY_COARSE)
            return
        law = mp.nodes_law([(tr.option.max_size, tr.nodes) for tr in self.trials.values()])
        size = mp.size_for_nodes(law, self.auto_target)
        self.options = [o for o in self.options if o.level is not MeshLevel.AUTO]
        self.trials.pop(MeshLevel.AUTO, None)
        auto_card = self.cards.pop(MeshLevel.AUTO, None)
        if auto_card is not None:
            self.card_group.removeButton(auto_card)
            auto_card.deleteLater()
        self.auto_attempt = 1
        self._run([("auto", auto_option(self.summary, size, "mesh.reason.objective"))])

    def create_mesh(self):
        t = self.tr.t
        option = self._selected_option()
        if option is None or self.job is not None:
            return
        trial = self.trials.get(option.level)
        if trial is not None:
            option = trial.option  # keeps the straight-edge fix found in the trial
            if self._status(trial) is BudgetStatus.TOO_BIG:
                answer = QMessageBox.question(self.form, t("ma.title"), t("ma.confirm_too_big"))
                if answer != QMessageBox.Yes:
                    return
        mesh, self.updated = mesh_runner.create_or_update_mesh(
            self.doc, self.solid, option, __version__, refine=self.refine)
        self._run([("create", (option, mesh))])

    def cancel(self):
        if self.job is not None:
            self.job.cancel()

    # --- task queue -----------------------------------------------------------------

    def _run(self, tasks):
        self.tasks = list(tasks)
        self.run_started = time.monotonic()
        self.steps_done = 0
        self.probes_pending = tasks[0][0] == "gmsh"
        self.steps_total = len(self.tasks) + (2 * MAX_PROBES if self.probes_pending else 0)
        self._set_busy(True)
        self._next_task()
        self.timer.start()

    def _next_task(self):
        for _ in range(100):  # bounded (rule 6): skipped tasks are consumed here
            if (self.probes_pending and self.trials
                    and not any(kind == "gmsh" for kind, _ in self.tasks)):
                self.probes_pending = False  # all sizes meshed (or skipped): measure CalculiX
                self._queue_probes()
            if (not self.tasks and self.finer_pending and not self.probes_pending):
                self._queue_finer()  # probes done: mesh only the finer sizes that may fit
            if not self.tasks:
                break
            kind, payload = self.tasks.pop(0)
            if kind == "gmsh" and self._too_big_for_gmsh(payload):
                self.skipped.add(payload.level)
                self.steps_done += 1
                continue
            if kind == "probe_gmsh" and not mp.probe_allowed(self.model, payload[0],
                                                             self.machine.available_mb):
                self.tasks = [task for task in self.tasks if task[0] != "probe_gmsh"]
                continue  # bigger trials would only be heavier
            self.task = (kind, payload)
            self.job = self._make_job(kind, payload)
            self.job.start()
            self._show_progress()
            return
        self._finished()

    def _make_job(self, kind, payload):
        gmsh_limit = GMSH_MEMORY_SHARE * self.machine.available_mb
        if kind in ("gmsh", "auto"):
            return self.trial_doc.job(payload, GMSH_TIME_LIMIT_S, gmsh_limit, self.refine)
        if kind == "probe_gmsh":
            return self.trial_doc.job(payload[1], GMSH_TIME_LIMIT_S, gmsh_limit, ())
        if kind == "probe":
            return mesh_runner.ProbeJob(payload, PROBE_TIME_LIMIT_S,
                                        PROBE_MEMORY_SHARE * self.machine.available_mb)
        option, mesh = payload
        return mesh_runner.GmshJob(mesh, GMSH_TIME_LIMIT_S, gmsh_limit, load_into_object=True)

    def _tick(self):
        if self.job is None:
            self.timer.stop()
            return
        state = self.job.poll()
        if state in ("running", "mesh", "solve"):
            self._show_progress()
            return
        kind, payload = self.task
        job, self.job = self.job, None
        self.steps_done += 1
        if kind == "probe":
            self._probe_done(payload, job)
        elif kind == "probe_gmsh":
            if state == job.DONE:
                self.tasks.insert(0, ("probe", job))  # now solve it with CalculiX
            else:
                self.tasks = [task for task in self.tasks if task[0] != "probe_gmsh"]
        elif state != job.DONE:
            self._failed(kind, payload, job, state)
            return
        elif kind == "gmsh":
            self._gmsh_done(payload, job)
        elif kind == "auto":
            self._auto_done(payload, job)
        else:
            self._created(payload, job)
            return
        self._next_task()

    def _gmsh_done(self, option, job):
        if job.run.inverted and not option.straight_edges:
            self.tasks.insert(0, ("gmsh", with_straight_edges(option)))  # automatic fix
            self.fixing = True
            return
        self.trials[option.level] = _Trial(option, job, fixed=self.fixing)
        self.fixing = False
        self._fill_table()

    def _queue_probes(self):
        """CalculiX trials on small dedicated meshes of this part (no curvature
        refinement): they fit on any computer and measure THIS part on THIS computer."""
        for target in mp.PROBE_TARGETS[:MAX_PROBES]:
            size = mp.probe_size(self.summary.volume, target)
            option = replace(auto_option(self.summary, size, "mesh.reason.objective"),
                             curvature=0, local_size=0.0, straight_edges=True)
            self.tasks.append(("probe_gmsh", (target, option)))

    def _probe_done(self, gmsh_job, job):
        if job.state == job.DONE:
            sample = SolverSample(job.nodes, job.seconds, job.peak_mb)
            self.probe_samples.append(sample)
            machine_calibration.save(self.machine, [sample])  # this computer learns
            self.model = mp.part_model(self.probe_samples)
            self._show_machine()
            self._fill_table()
        else:  # a probe that failed or hit a limit stops further probes (they are bigger)
            self.tasks = [task for task in self.tasks if task[0] not in ("probe", "probe_gmsh")]
            self.details.setPlainText(job.process.log_text()[-2000:] if job.process else "")

    def _auto_done(self, option, job):
        t = self.tr.t
        if job.run.inverted and not option.straight_edges:
            self.tasks.insert(0, ("auto", with_straight_edges(option)))
            return
        nodes = job.run.nodes
        if nodes > self.auto_target and self.auto_attempt < AUTO_ATTEMPTS:
            self.auto_attempt += 1
            smaller = (1.03 * nodes / self.auto_target) ** (1.0 / 3.0)  # 3 % below the target
            self.tasks.insert(0, ("auto", auto_option(self.summary, option.max_size * smaller,
                                                      "mesh.reason.objective")))
            return
        self.trials[MeshLevel.AUTO] = _Trial(option, job)
        self.options = [o for o in self.options if o.level is not MeshLevel.AUTO] + [option]
        self._fill_table()
        self._select_level(MeshLevel.AUTO)
        limit = mp.binding_limit(self.model, self.machine.available_mb, self.objective,
                                 FITS_FRACTION)
        self.status_label.setText("%s %s" % (t(
            "ma.auto_done", objective=self.objective_box.currentText(),
            size=mt.mm(self.tr, option.max_size), nodes=self.tr.integer(nodes),
            seconds=format_duration(mp.total_seconds(self.model, nodes, None, self._speed()))),
            t("ma.limit." + limit)))
        self.tasks = []

    def _failed(self, kind, payload, job, state):
        t = self.tr.t
        option = payload[0] if kind == "create" else payload
        level = t("ma.level." + option.level.value).lower()
        self.tasks = []
        self._set_busy(False)
        self.timer.stop()
        self.details.setPlainText("%s\n\n%s" % (mt.gmsh_settings(option, self.tr), job.log_tail()))
        self.status_label.setText(t("ma.cancelled") if state == job.CANCELLED else
                                  t("ma.failed", level=level, reason=t("ma.reason." + state)))

    def _finished(self):
        t = self.tr.t
        self.task = None
        self._set_busy(False)
        self.timer.stop()
        if self.test_run:
            self.test_run = False
            self.status_label.setText(t("ma.tested", elapsed=format_duration(
                time.monotonic() - self.run_started)))
            self._recommend()

    def _recommend(self):
        t = self.tr.t
        levels = [o.level for o in self.options if o.level is not MeshLevel.AUTO]
        statuses = {lv: self._status(self.trials[lv]) for lv in levels if lv in self.trials}
        seconds = {lv: self._total_seconds(self.trials[lv]) for lv in statuses}
        seconds = {lv: s for lv, s in seconds.items() if s is not None}  # unknown: not fast
        level, key = mp.recommend(statuses, seconds)
        self.recommended = (level, key)
        self._fill_table()
        self._select_level(level)
        trial = self.trials.get(level)
        if trial is None:
            return
        self.recommend_label.setText(t(
            "ma.recommend.box", level=t("ma.level." + level.value),
            size=mt.mm(self.tr, trial.option.max_size), nodes=self.tr.integer(trial.nodes),
            seconds=(t("ma.time_unknown") if self._total_seconds(trial) is None
                     else format_duration(self._total_seconds(trial))),
            status=t("ma.status." + statuses[level].value), why=t(key)))

    def _total_seconds(self, trial):
        """None while this computer's speed is unknown."""
        if not self.model.time_known:
            return None
        return mp.total_seconds(self.model, trial.nodes, None, self._speed())

    def _created(self, payload, job):
        t = self.tr.t
        option, mesh = payload
        self._set_busy(False)
        self.timer.stop()
        nodes = job.run.nodes
        status = mp.classify(self.model, nodes, self.machine.available_mb)
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
        key = "ma.updated" if getattr(self, "updated", False) else "ma.created"
        text = "%s %s" % (t(key, label=mesh.Label, nodes=self.tr.integer(nodes),
                            status=t("ma.status." + status.value)), where)
        if mesh_runner.has_results(self.doc):
            text += " " + t("ma.results_stale")
        App.Console.PrintMessage("PartReview: %s\n" % text)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(mesh)  # the new mesh is selected in the tree
        if inside and not mesh_runner.has_results(self.doc):  # all set: status bar note
            Gui.getMainWindow().statusBar().showMessage(text, 20000)
        else:  # something to do (mesh outside the analysis): say it clearly
            QMessageBox.information(Gui.getMainWindow(), t("ma.title"), text)
        self.reject()  # task done: close the panel

    def _queue_finer(self):
        known = [(tr.option.max_size, tr.nodes) for tr in self.trials.values()]
        for option in self.finer_pending:
            nodes = mp.nodes_law(known)(option.max_size) if len(known) >= 2 else None
            if nodes is None:
                continue
            upper = self.model.memory_mb(nodes) * (1 + self.model.error)
            if upper <= TIGHT_FRACTION * self.machine.available_mb:
                self.tasks.append(("gmsh", option))
                self.steps_total += 1
            else:
                self.predicted[option.level] = int(nodes)  # shown as predicted, not meshed
        self.finer_pending = []

    def _predicted_nodes(self, option):
        trial = self.trials.get(option.level)
        if trial is not None:
            return trial.nodes
        known = [(tr.option.max_size, tr.nodes) for tr in self.trials.values()]
        if len(known) >= 2:
            return mp.nodes_law(known)(option.max_size)
        return estimate_nodes(self.summary.volume, option.max_size, 2.0)

    def _too_big_for_gmsh(self, option):
        """Skip a Gmsh trial when the mesh would be absurd, or clearly too big to solve
        here (twice the 'tight' memory): it saves the longest trials."""
        known = [(tr.option.max_size, tr.nodes) for tr in self.trials.values()]
        if len(known) < 2:
            return option.nodes_low > mp.GMSH_MAX_NODES
        predicted = mp.nodes_law(known)(option.max_size)
        hopeless = mp.is_hopeless(self.model, predicted, self.machine.available_mb,
                                  2 * TIGHT_FRACTION)
        return predicted > mp.GMSH_MAX_NODES or hopeless

    # --- view helpers ---------------------------------------------------------------

    def _prior(self):
        """Before probing this part: memory band, time from THIS computer's history."""
        law = mp.machine_time_law(self.machine_samples) if self.machine_samples else None
        return mp.part_model([], law)

    def _speed(self):
        return speed_factor(self.probe_samples or self.machine_samples)

    def _status(self, trial):
        measured = None  # options are predicted from the probes, never assumed
        return mp.classify(self.model, trial.nodes, self.machine.available_mb, measured)

    def _fill_table(self):
        t = self.tr.t
        self._show_current()
        self.table.setRowCount(len(self.options))
        for row, option in enumerate(self.options):
            trial = self.trials.get(option.level)
            name = t("ma.level." + option.level.value)
            if self.recommended and self.recommended[0] is option.level:
                name = "★ " + name
            cells = [name, mt.mm(self.tr, option.max_size)]
            color = None
            if trial is not None:
                nodes = trial.nodes
                if self.model.memory_low is not None:  # not measured: band of shapes
                    memory = "~%s – %s" % (mt.memory(self.tr, self.model.memory_low(nodes)),
                                           mt.memory(self.tr, self.model.memory_mb(nodes)))
                else:
                    memory = "~" + mt.memory(self.tr, self.model.memory_mb(nodes))
                total = self._total_seconds(trial)
                seconds = t("ma.time_unknown") if total is None else "~" + format_duration(total)
                status = self._status(trial)
                text = t("ma.status." + status.value)
                if trial.fixed:
                    text += t("ma.status.fixed")
                cells += [self.tr.integer(nodes), memory, seconds, text,
                          mt.measured(self.tr, trial.job.elapsed, trial.job.peak_mb)]
                color = STATUS_COLORS[status]
            elif option.level in self.predicted:  # predicted from the measured law
                nodes = self.predicted[option.level]
                status = mp.classify(self.model, nodes, self.machine.available_mb)
                total = (mp.total_seconds(self.model, nodes, None, self._speed())
                         if self.model.time_known else None)
                cells += ["~%s" % self.tr.integer(round(nodes, -3)),
                          "~" + mt.memory(self.tr, self.model.memory_mb(nodes)),
                          t("ma.time_unknown") if total is None else "~" + format_duration(total),
                          t("ma.status." + status.value) + t("ma.status.predicted"), ""]
                color = STATUS_COLORS[status]
            else:
                text = (t("ma.status.big_for_gmsh") if option.level in self.skipped
                        else t("ma.status.not_tested"))
                cells += [mt.nodes_estimate(option, self.tr), "", "", text, ""]
            for col, value in enumerate(cells):
                item = QTableWidgetItem(value)
                item.setToolTip(mt.option_reason(option, self.summary, self.tr))
                if color is not None and col == 5:
                    item.setForeground(color)
                self.table.setItem(row, col, item)
            self._card(row, option, cells, trial)

    def _card(self, row, option, cells, trial):
        """Big clickable card for one option (same look as the report level cards)."""
        t = self.tr.t
        button = self.cards.get(option.level)
        if button is None:
            button = QToolButton()
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setIcon(mesh_icon(DENSITY[option.level]))
            button.setIconSize(QSize(36, 36))
            button.setMinimumHeight(112)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(lambda _=False, lv=option.level: self._select_level(lv))
            self.card_group.addButton(button)
            self.cards[option.level] = button
            index = len(self.cards) - 1
            self.cards_layout.addWidget(button, index // 3, index % 3)
            self.cards_layout.setColumnStretch(index % 3, 1)
        nodes = trial.nodes if trial is not None else self.predicted.get(option.level)
        if nodes is not None:
            lines = [cells[0], "%s · %s" % (cells[1], t(
                         "ma.card.nodes", nodes=self.tr.integer(round(nodes, -3) / 1000))),
                     "%s · %s" % (cells[4], cells[5].split(" (")[0])]
        else:
            lines = [cells[0], cells[1], t("ma.card.not_tested")]
        button.setText("\n".join(lines))
        tip = mt.option_reason(option, self.summary, self.tr)
        if option.level in self.predicted:
            tip += "\n" + t("ma.predicted_tip")
        button.setToolTip(tip)

    def _show_current(self):
        """The mesh the user already has for this part, judged with the same model."""
        t = self.tr.t
        mesh = getattr(self, "current_mesh", None)
        if mesh is None or mesh.Document is None:
            self.current_label.setText("")
            self.current_label.setVisible(False)
            return
        nodes = mesh.FemMesh.NodeCount
        status = mp.classify(self.model, nodes, self.machine.available_mb)
        if self.model.memory_low is not None:
            memory = "%s – %s" % (mt.memory(self.tr, self.model.memory_low(nodes)),
                                  mt.memory(self.tr, self.model.memory_mb(nodes)))
        else:
            memory = mt.memory(self.tr, self.model.memory_mb(nodes))
        total = (mp.total_seconds(self.model, nodes, None, self._speed())
                 if self.model.time_known else None)
        self.current_label.setText(t(
            "ma.current", label=mesh.Label, nodes=self.tr.integer(nodes), memory=memory,
            seconds=t("ma.time_unknown") if total is None else format_duration(total),
            status=t("ma.status." + status.value)))
        self.current_label.setVisible(True)

    def _select_level(self, level):
        for row, option in enumerate(self.options):
            if option.level is level:
                self.table.selectRow(row)
                if level in self.cards:
                    self.cards[level].setChecked(True)
                return

    def _selected_option(self):
        rows = {i.row() for i in self.table.selectedItems()}
        return self.options[min(rows)] if rows else None

    def _show_selected(self):
        option = self._selected_option()
        if option is None:
            return
        trial = self.trials.get(option.level)
        shown = trial.option if trial is not None else option
        if self.job is None:
            self.details.setPlainText(mt.gmsh_settings(shown, self.tr))

    def _show_machine(self):
        rows = mt.machine_rows(self.machine, self.model, self.probe_samples,
                               self.machine_samples, self.machine_date, self.tr)
        for (title, value), (label, text) in zip(self.machine_rows, rows):
            title.setText(label)
            value.setText(text)

    def _show_progress(self):
        t = self.tr.t
        kind, payload = self.task
        if kind in ("probe", "probe_gmsh"):
            level, what_key = MeshLevel.AUTO, "ma.what." + kind
        elif kind == "create":
            level, what_key = payload[0].level, "ma.what.create"
        else:
            level, what_key = payload.level, "ma.what." + kind
        what = t(what_key, level=t("ma.level." + level.value).lower(), attempt=self.auto_attempt,
                 n=len(self.probe_samples) + 1)
        elapsed = time.monotonic() - self.run_started
        self.progress.setRange(0, max(1, self.steps_total))
        self.progress.setValue(min(self.steps_done, self.steps_total))
        self.status_label.setText(t("ma.step", done=self.steps_done + 1,
                                    total=max(self.steps_total, self.steps_done + 1), what=what,
                                    elapsed=format_duration(elapsed),
                                    remaining=format_duration(self._remaining())))

    def _remaining(self):
        known = [tr for tr in self.trials.values() if tr.job.elapsed > 0 and tr.nodes]
        per_node = (sum(tr.job.elapsed for tr in known) / sum(tr.nodes for tr in known)
                    if known else GMSH_S_PER_NODE)
        pending_gmsh, pending_probes = [], []
        for kind, payload in self.tasks:
            if kind in ("gmsh", "auto"):
                pending_gmsh.append(self._predicted_nodes(payload))
            elif kind == "probe_gmsh":
                pending_probes.append(payload[0])
        current = self.job.elapsed if self.job is not None else 0.0
        current_left = 0.0
        if self.task and self.task[0] == "probe":
            n = self.task[1].run.nodes
            current_left = max(0.0, self.model.seconds(n) - current)
        elif self.task and self.task[0] in ("gmsh", "auto"):
            current_left = max(0.0, per_node * self._predicted_nodes(self.task[1]) - current)
        if self.probes_pending:  # probes are queued after the meshes: count them already
            pending_probes += list(mp.PROBE_TARGETS[:MAX_PROBES])
        # only probes the safety rule will actually run
        pending_probes = [n for n in pending_probes
                          if mp.probe_allowed(self.model, n, self.machine.available_mb)]
        return current_left + mp.remaining_seconds(per_node, pending_gmsh, self.model,
                                                   pending_probes)

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
        analysed = self.summary is not None
        for widget in (self.test_button, self.auto_button, self.create_button,
                       self.objective_box):
            widget.setEnabled(not busy and analysed)
        self.analyze_button.setEnabled(not busy)
        self.part_combo.setEnabled(not busy)

    def _enable(self, analysed):
        for widget in (self.issues_box, self.options_box, self.details_box, self.create_title):
            widget.setVisible(analysed)
        self._set_busy(False)

    def _close_trial_doc(self):
        if self.trial_doc is not None:
            self.trial_doc.close()
            self.trial_doc = None

    def _cleanup(self):
        if self.job is not None:
            self.job.cancel()
            self.job = None
        self.timer.stop()
        self._close_trial_doc()
