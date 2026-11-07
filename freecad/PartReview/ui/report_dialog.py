# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Dialog for the FEM report. Thin: widgets read/write one ReportConfig (rule 2)."""

import os
import traceback
from dataclasses import replace

import FreeCAD as App  # type: ignore
import FreeCADGui as Gui  # type: ignore
from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt, QUrl  # type: ignore
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPen, QPixmap  # type: ignore
from PySide6.QtWidgets import (  # type: ignore
    QApplication,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..adapters import fem_reader, preferences, template_store
from ..adapters.logo_loader import inspect_logo, load_logo
from ..adapters.report_job import Cancelled, ConfigError, generate_fem_report
from ..domain.blocks import DEFAULT_ACCENT_HEX
from ..domain.colors import accent_palette, readable_on, to_hex, to_rgb
from ..domain.i18n import Translator
from ..domain.logo import COMPACT_COVER_BOX_MM, check_sharpness
from ..domain.models import ReportConfig, ReportLevel, UnitSystem
from ..domain.templates import ReportTemplate

LANGUAGE_NAMES = (("pt_BR", "Português (Brasil)"), ("en", "English"))
# Pages drawn on each card: a visual hint of the report size.
LEVEL_PAGES = {ReportLevel.QUICK: 1, ReportLevel.STANDARD: 3, ReportLevel.FULL: 6}


def ui_language():
    """Dialog language follows FreeCAD's interface language."""
    name = App.ParamGet("User parameter:BaseApp/Preferences/General").GetString("Language", "")
    return "pt_BR" if name.lower().startswith("portuguese") else "en"


def page_stack_icon(pages, accent=QColor(31, 74, 125), size=64):
    """A small drawing of a stack of ``pages`` sheets with text lines and a chart."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    w, h = size * 0.5, size * 0.66
    step = min(5.0, (size - w - 4) / max(1, pages - 1)) if pages > 1 else 0
    for i in range(pages):
        x = 4 + (pages - 1 - i) * step
        y = 4 + (pages - 1 - i) * step * 0.6
        p.setPen(QPen(QColor(120, 120, 120), 1))
        p.setBrush(QColor(255, 255, 255))
        p.drawRect(QRectF(x, y, w, h))
    x, y = 4, 4
    p.setPen(QPen(accent, 2))
    for k in range(4):
        p.drawLine(int(x + 5), int(y + 8 + k * 6), int(x + w - 5), int(y + 8 + k * 6))
    p.setBrush(accent)
    p.setPen(Qt.NoPen)
    for k, bar in enumerate((6, 10, 8)):
        p.drawRect(QRectF(x + 6 + k * 7, y + h - 5 - bar, 5, bar))
    p.end()
    return QIcon(pixmap)


class _WheelGuard(QObject):
    """Mouse wheel over a combo box scrolls the dialog instead of changing the
    choice, unless the user clicked the combo first (no accidental changes)."""

    target = None  # scroll bar that receives the redirected wheel events

    def watch(self, widget):
        widget.setFocusPolicy(Qt.StrongFocus)
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and not obj.hasFocus():
            if self.target is not None:
                QApplication.sendEvent(self.target, event)
            return True
        return False


class ReportDialog(QDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.doc = doc
        self.tr_ui = Translator(ui_language())
        t = self.tr_ui.t
        self.config = ReportConfig(language=self.tr_ui.language)
        self._loading = False
        self.setWindowTitle(t("ui.dialog_title"))
        # Everything except the Generate/Cancel buttons scrolls, so the buttons
        # stay reachable on small screens or with "Appearance" open (P2).
        content = QWidget()
        layout = QVBoxLayout(content)
        self._wheel_guard = _WheelGuard(self)

        # --- template row
        self.template_box = QComboBox()
        save_template = QPushButton(t("ui.template_save"))
        delete_template = QPushButton(t("ui.template_delete"))
        save_template.clicked.connect(self._save_template)
        delete_template.clicked.connect(self._delete_template)
        self.template_box.currentIndexChanged.connect(self._apply_template)
        row = QHBoxLayout()
        row.addWidget(QLabel(t("ui.template")))
        row.addWidget(self.template_box, 1)
        row.addWidget(save_template)
        row.addWidget(delete_template)
        layout.addLayout(row)

        # --- level cards (step i)
        level_box = QGroupBox(t("ui.level"))
        cards = QHBoxLayout(level_box)
        self.level_group = QButtonGroup(self)
        self.level_buttons = {}
        for level in ReportLevel:
            button = QToolButton()
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setIcon(page_stack_icon(LEVEL_PAGES[level]))
            button.setIconSize(QSize(64, 64))
            button.setText("%s\n%s" % (t("report.level." + level.value),
                                       t("ui.level_pages." + level.value)))
            button.setToolTip(t("ui.level_desc." + level.value))
            button.setMinimumWidth(150)
            self.level_group.addButton(button)
            self.level_buttons[level] = button
            cards.addWidget(button)
        # The checked card must stand out in any FreeCAD theme (light or dark).
        level_box.setStyleSheet(
            "QToolButton{border:1px solid palette(mid);border-radius:6px;padding:6px}"
            "QToolButton:checked{border:3px solid palette(highlight);"
            "background:palette(highlight);color:palette(highlighted-text);font-weight:bold}")
        self.level_desc = QLabel()
        self.level_desc.setWordWrap(True)
        self.level_group.buttonClicked.connect(self._sync)
        outer = QVBoxLayout()
        outer.addWidget(level_box)
        outer.addWidget(self.level_desc)
        layout.addLayout(outer)

        # --- main fields
        form = QFormLayout()
        self.result_box = QComboBox()
        for name, label in fem_reader.list_mechanical_results(doc):
            self.result_box.addItem(label, name)
        self.language_box = QComboBox()
        for code, name in LANGUAGE_NAMES:
            self.language_box.addItem(name, code)
        self.units_box = QComboBox()
        for system in UnitSystem:
            self.units_box.addItem(t("ui.units." + system.value), system)
        for box in (self.result_box, self.language_box, self.units_box):
            box.currentIndexChanged.connect(self._sync)
        for box in (self.template_box, self.result_box, self.language_box, self.units_box):
            self._wheel_guard.watch(box)
        self.title_edit = QLineEdit()
        self.author_edit = QLineEdit()
        self.company_edit = QLineEdit()
        self.logo_edit = QLineEdit()
        self.yield_edit = QLineEdit()
        self.yield_edit.setPlaceholderText(t("ui.yield_hint"))
        self.output_edit = QLineEdit(self._default_output())
        for edit in (self.title_edit, self.author_edit, self.company_edit, self.logo_edit,
                     self.yield_edit, self.output_edit):
            edit.textChanged.connect(self._sync)
        form.addRow(t("ui.result"), self.result_box)
        form.addRow(t("ui.language"), self.language_box)
        form.addRow(t("ui.units"), self.units_box)
        form.addRow(t("ui.title"), self.title_edit)
        form.addRow(t("ui.author"), self.author_edit)
        form.addRow(t("ui.company"), self.company_edit)
        form.addRow(t("ui.logo"), self._with_button(self.logo_edit, self._browse_logo))
        self.logo_preview = QLabel()
        self.logo_preview.setFixedSize(72, 36)
        self.logo_preview.setAlignment(Qt.AlignCenter)
        self.logo_info = QLabel()
        self.logo_info.setWordWrap(True)
        logo_row = QWidget()
        logo_layout = QHBoxLayout(logo_row)
        logo_layout.setContentsMargins(0, 0, 0, 0)
        logo_layout.addWidget(self.logo_preview)
        logo_layout.addWidget(self.logo_info, 1)
        form.addRow("", logo_row)
        self.logo_edit.textChanged.connect(self._update_logo_info)
        form.addRow(t("ui.yield"), self.yield_edit)
        layout.addLayout(form)

        # --- look and fixed texts (templates)
        advanced = QGroupBox(t("ui.advanced"))
        advanced.setCheckable(True)
        advanced.setChecked(False)
        adv = QFormLayout()
        self.color_button = QPushButton()
        self.color_button.clicked.connect(self._pick_color)
        self.intro_edit = QPlainTextEdit()
        self.disclaimer_edit = QPlainTextEdit()
        for edit in (self.intro_edit, self.disclaimer_edit):
            edit.setFixedHeight(54)
            edit.textChanged.connect(self._sync)
        self.color_note = QLabel()
        self.color_note.setWordWrap(True)
        adv.addRow(t("ui.accent"), self.color_button)
        adv.addRow("", self.color_note)
        adv.addRow(t("ui.intro"), self.intro_edit)
        adv.addRow(t("ui.disclaimer"), self.disclaimer_edit)
        adv_widget = QWidget()
        adv_widget.setLayout(adv)
        adv_widget.setVisible(False)
        advanced.toggled.connect(adv_widget.setVisible)
        advanced.toggled.connect(self._fit_to_screen)
        box = QVBoxLayout(advanced)
        box.addWidget(adv_widget)
        layout.addWidget(advanced)

        # --- output and exports
        out = QFormLayout()
        out.addRow(t("ui.output"), self._with_button(self.output_edit, self._browse))
        self.csv_check = QCheckBox(t("ui.export_csv"))
        self.html_check = QCheckBox(t("ui.export_html"))
        for check in (self.csv_check, self.html_check):
            check.toggled.connect(self._sync)
        exports = QHBoxLayout()
        exports.addWidget(self.html_check)
        exports.addWidget(self.csv_check)
        exports.addStretch(1)
        out.addRow(t("ui.export"), exports)
        layout.addLayout(out)
        layout.addStretch(1)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setWidget(content)
        self._wheel_guard.target = self._scroll.verticalScrollBar()
        main = QVBoxLayout(self)
        main.addWidget(self._scroll, 1)

        buttons = QDialogButtonBox()
        buttons.addButton(t("ui.generate"), QDialogButtonBox.AcceptRole)
        buttons.addButton(t("ui.cancel"), QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self._generate)
        buttons.rejected.connect(self.reject)
        main.addWidget(buttons)

        # Remember the logo of the last report (repetitive analyses); a template
        # chosen afterwards still replaces it.
        last_logo = preferences.last_logo_path()
        self._last_logo_missing = ""
        if last_logo and os.path.isfile(last_logo):
            self.config.logo_path = last_logo
        elif last_logo:
            self._last_logo_missing = last_logo

        self._load_widgets_from_config()
        self._reload_templates()
        self._update_logo_info()
        self._fit_to_screen()

    # --- helpers -----------------------------------------------------------------

    def _fit_to_screen(self, *_):
        """Size the dialog to its content, but never taller than the screen."""
        content = self._scroll.widget()
        content.adjustSize()
        wanted = content.sizeHint().height() + self.sizeHint().height() \
            - self._scroll.sizeHint().height()
        screen = self.screen() or QApplication.primaryScreen()
        limit = int(screen.availableGeometry().height() * 0.9) if screen else wanted
        self.resize(max(self.width(), 620), max(min(wanted, limit), min(400, limit)))

    def _with_button(self, edit, slot):
        button = QPushButton(self.tr_ui.t("ui.browse"))
        button.clicked.connect(slot)
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit)
        row.addWidget(button)
        return widget

    def _update_logo_info(self, *_):
        """Preview + sharpness note under the logo field (information, not an error)."""
        t = self.tr_ui.t
        path = self.logo_edit.text().strip()
        self.logo_preview.clear()
        if not path:
            self.logo_info.setText(t("ui.logo_last_missing", path=self._last_logo_missing)
                                   if self._last_logo_missing else "")
            return
        self._last_logo_missing = ""
        error, width, height = inspect_logo(path)
        if error:
            self.logo_info.setText(t(error))
            return
        image = load_logo(path, COMPACT_COVER_BOX_MM)
        if image is not None:
            self.logo_preview.setPixmap(QPixmap.fromImage(image).scaled(
                self.logo_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        sharp = check_sharpness(path, width, height)
        self.logo_info.setText(t("ui.logo_info." + sharp.level, w=width, h=height,
                                 dpi=int(round(sharp.dpi)), need=sharp.min_width_px))

    def _show_color(self):
        color = self.config.accent_color or DEFAULT_ACCENT_HEX
        palette = accent_palette(to_rgb(color))
        self.color_button.setText(color)
        self.color_button.setStyleSheet("background:%s;color:%s" % (
            color, to_hex(readable_on(palette.base))))
        self.color_note.setText(self.tr_ui.t("ui.accent_adjusted", text=to_hex(palette.text))
                                if palette.adjusted else "")

    # --- config binding (the only state) --------------------------------------

    def _load_widgets_from_config(self):
        """Config -> widgets (after a template is applied)."""
        c = self.config
        self._loading = True
        try:
            self.level_buttons[c.level].setChecked(True)
            self.language_box.setCurrentIndex([code for code, _ in LANGUAGE_NAMES].index(c.language))
            self.units_box.setCurrentIndex(list(UnitSystem).index(c.unit_system))
            self.author_edit.setText(c.author)
            self.company_edit.setText(c.company)
            self.logo_edit.setText(c.logo_path)
            self.intro_edit.setPlainText(c.intro_text)
            self.disclaimer_edit.setPlainText(c.disclaimer_text)
        finally:
            self._loading = False
        self._sync()

    def _sync(self, *_):
        """Widgets -> config."""
        if self._loading:
            return
        c = self.config
        c.result_name = self.result_box.currentData() or ""
        c.language = self.language_box.currentData()
        c.unit_system = self.units_box.currentData()
        c.level = next(lv for lv, b in self.level_buttons.items() if b.isChecked())
        c.title = self.title_edit.text().strip()
        c.author = self.author_edit.text().strip()
        c.company = self.company_edit.text().strip()
        c.logo_path = self.logo_edit.text().strip()
        c.yield_strength = self.yield_edit.text().strip()
        c.output_path = self.output_edit.text().strip()
        c.intro_text = self.intro_edit.toPlainText().strip()
        c.disclaimer_text = self.disclaimer_edit.toPlainText().strip()
        c.export_csv = self.csv_check.isChecked()
        c.export_html = self.html_check.isChecked()
        self.level_desc.setText(self.tr_ui.t("ui.level_desc." + c.level.value))
        self._show_color()

    def _default_output(self):
        base = os.path.splitext(self.doc.FileName)[0] if self.doc.FileName else \
            os.path.join(os.path.expanduser("~"), self.doc.Label)
        return base + "_PartReview.pdf"

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(self, self.tr_ui.t("ui.output"),
                                              self.config.output_path, "PDF (*.pdf)")
        if path:
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            self.output_edit.setText(path)

    def _browse_logo(self):
        path, _ = QFileDialog.getOpenFileName(self, self.tr_ui.t("ui.logo"),
                                              self.config.logo_path,
                                              self.tr_ui.t("ui.logo_filter"))
        if path:
            self.logo_edit.setText(path)

    def _pick_color(self):
        color = QColorDialog.getColor(QColor(self.config.accent_color or DEFAULT_ACCENT_HEX), self,
                                      self.tr_ui.t("ui.accent"))
        if color.isValid():
            self.config.accent_color = color.name()
            self._show_color()

    # --- templates (step g) -------------------------------------------------------

    def _reload_templates(self, select=""):
        self._templates = {tpl.name: tpl for tpl in template_store.list_templates()}
        self.template_box.blockSignals(True)
        self.template_box.clear()
        self.template_box.addItem(self.tr_ui.t("ui.template_none"), "")
        for name in self._templates:
            self.template_box.addItem(name, name)
        index = self.template_box.findData(select)
        self.template_box.setCurrentIndex(max(0, index))
        self.template_box.blockSignals(False)

    def _apply_template(self, *_):
        name = self.template_box.currentData()
        if name and name in self._templates:
            self._templates[name].apply_to(self.config)
            self._load_widgets_from_config()

    def _save_template(self):
        t = self.tr_ui.t
        current = self.template_box.currentData() or ""
        name, ok = QInputDialog.getText(self, t("ui.template"), t("ui.template_name"),
                                        text=current)
        if not ok or not name.strip():
            return
        template = ReportTemplate.from_config(name.strip(), self.config)
        errors = template.validate()
        if errors:
            QMessageBox.warning(self, t("ui.template"), t(errors[0]))
            return
        try:
            path = template_store.save_template(template)
        except OSError as err:
            QMessageBox.warning(self, t("ui.template"), str(err))
            return
        self._reload_templates(select=template.name)
        QMessageBox.information(self, t("ui.template"), t("ui.template_saved", path=path))

    def _delete_template(self):
        t = self.tr_ui.t
        name = self.template_box.currentData()
        if not name:
            return
        answer = QMessageBox.question(self, t("ui.template"),
                                      t("ui.template_confirm_delete", name=name))
        if answer == QMessageBox.Yes:
            try:
                template_store.delete_template(name)
            except OSError as err:
                QMessageBox.warning(self, t("ui.template"), str(err))
            self._reload_templates()

    # --- run --------------------------------------------------------------------

    def _generate(self):
        t = self.tr_ui.t
        self._sync()
        errors = self.config.validate()
        if errors:
            QMessageBox.warning(self, t("ui.dialog_title"), "\n".join(t(e) for e in errors))
            return
        run_config = self.config
        if run_config.logo_path:
            logo_error = inspect_logo(run_config.logo_path)[0]
            if logo_error:
                answer = QMessageBox.question(
                    self, t("ui.dialog_title"),
                    t("ui.logo_generate_without", error=t(logo_error)))
                if answer != QMessageBox.Yes:
                    return
                run_config = replace(self.config, logo_path="")  # this run only

        progress = QProgressDialog("", t("ui.cancel"), 0, 100, self)
        progress.setWindowTitle(t("ui.dialog_title"))
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)

        def report_progress(message, fraction):
            if progress.wasCanceled():
                raise Cancelled()
            if message:
                progress.setLabelText(message)
            progress.setValue(int(fraction * 100))
            QApplication.processEvents()

        try:
            written = generate_fem_report(self.doc, run_config, report_progress)
        except Cancelled:
            QMessageBox.information(self, t("ui.dialog_title"), t("ui.cancelled"))
            return
        except (ConfigError, fem_reader.FemReadError) as err:
            QMessageBox.warning(self, t("ui.dialog_title"), t(err.key))
            return
        except Exception as err:  # rule 5: unexpected -> console with context + clear message
            App.Console.PrintError("PartReview: report failed:\n%s" % traceback.format_exc())
            QMessageBox.critical(self, t("ui.dialog_title"), t("ui.failed", error=err))
            return
        finally:
            progress.close()

        preferences.remember_logo_path(run_config.logo_path)
        QMessageBox.information(self, t("ui.dialog_title"),
                                t("ui.done_many", paths="\n".join(written)))
        QDesktopServices.openUrl(QUrl.fromLocalFile(written[0]))
        self.accept()
