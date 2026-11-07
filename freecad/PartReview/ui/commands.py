# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""FreeCAD commands of the workbench."""

import os

import FreeCAD as App  # type: ignore
import FreeCADGui as Gui  # type: ignore
from PySide6.QtWidgets import QMessageBox  # type: ignore

from ..adapters import fem_reader
from ..domain.i18n import Translator

ICON = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "icons",
                    "partreview.svg")


class FemReportCommand:
    def GetResources(self):
        from .report_dialog import ui_language
        t = Translator(ui_language()).t
        return {"MenuText": t("ui.command"), "ToolTip": t("ui.command_tip"), "Pixmap": ICON}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        from .report_dialog import ReportDialog, ui_language
        t = Translator(ui_language()).t
        doc = App.ActiveDocument
        if doc is None:
            QMessageBox.information(Gui.getMainWindow(), t("ui.dialog_title"), t("ui.no_document"))
            return
        if not fem_reader.list_mechanical_results(doc):
            QMessageBox.information(Gui.getMainWindow(), t("ui.dialog_title"), t("ui.no_results"))
            return
        ReportDialog(doc).exec()


COMMANDS = {"PartReview_FemReport": FemReportCommand()}


def register():
    for name, command in COMMANDS.items():
        Gui.addCommand(name, command)
    return list(COMMANDS)
