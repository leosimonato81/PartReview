# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""FreeCAD commands of the workbench."""

import os

import FreeCAD as App  # type: ignore
import FreeCADGui as Gui  # type: ignore
from PySide6.QtWidgets import QMessageBox  # type: ignore

from ..adapters import fem_reader
from ..domain.i18n import Translator

_ICONS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "icons")
ICON = os.path.join(_ICONS, "partreview.svg")
ASSISTANT_ICON = os.path.join(_ICONS, "mesh_assistant.svg")
OPTIMIZER_ICON = os.path.join(_ICONS, "mesh_optimizer.svg")


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


class MeshAssistantCommand:
    """Mesh assistant task panel (v1.5.0, decision 007)."""

    def GetResources(self):
        from .report_dialog import ui_language
        t = Translator(ui_language()).t
        return {"MenuText": t("ma.command"), "ToolTip": t("ma.command_tip"),
                "Pixmap": ASSISTANT_ICON}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        from .mesh_assistant import MeshAssistantPanel
        Gui.Control.showDialog(MeshAssistantPanel(App.ActiveDocument))


class MeshOptimizerCommand:
    """Refine the mesh where the estimated error is high (decision 008)."""

    def GetResources(self):
        from .report_dialog import ui_language
        t = Translator(ui_language()).t
        return {"MenuText": t("mo.command"), "ToolTip": t("mo.command_tip"),
                "Pixmap": OPTIMIZER_ICON}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        from .mesh_optimizer import MeshOptimizerPanel
        Gui.Control.showDialog(MeshOptimizerPanel(App.ActiveDocument))


COMMANDS = {"PartReview_MeshAssistant": MeshAssistantCommand(),
            "PartReview_MeshOptimizer": MeshOptimizerCommand(),
            "PartReview_FemReport": FemReportCommand()}


def register():
    for name, command in COMMANDS.items():
        Gui.addCommand(name, command)
    return list(COMMANDS)
