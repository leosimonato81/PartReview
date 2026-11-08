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
CHECK_ICON = os.path.join(_ICONS, "check_mesh.svg")
ASSISTANT_ICON = os.path.join(_ICONS, "mesh_assistant.svg")


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


class CheckMeshCommand:
    """'Check before solving': will CalculiX fit in the free memory? (decision 007)."""

    def GetResources(self):
        from .report_dialog import ui_language
        t = Translator(ui_language()).t
        return {"MenuText": t("ui.check_command"), "ToolTip": t("ui.check_command_tip"),
                "Pixmap": CHECK_ICON}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        from ..adapters.machine import machine_profile
        from ..domain.mesh_budget import BudgetStatus, budget_message, check_budget
        from .report_dialog import ui_language
        tr = Translator(ui_language())
        parent, title = Gui.getMainWindow(), tr.t("ui.check_title")
        doc = App.ActiveDocument
        if doc is None:
            QMessageBox.information(parent, title, tr.t("ui.check_no_mesh"))
            return
        meshes = fem_reader.solver_meshes(doc, Gui.Selection.getSelection(doc.Name))
        if not meshes:
            QMessageBox.information(parent, title, tr.t("ui.check_no_mesh"))
            return
        if len(meshes) > 1:
            QMessageBox.information(parent, title, tr.t("ui.check_many_meshes"))
            return
        machine = machine_profile()
        check = check_budget(meshes[0].FemMesh.NodeCount, machine)
        text = "%s\n\n%s" % (meshes[0].Label, budget_message(check, machine, tr))
        box = {BudgetStatus.FITS: QMessageBox.information, BudgetStatus.TIGHT: QMessageBox.warning,
               BudgetStatus.TOO_BIG: QMessageBox.critical}[check.status]
        box(parent, title, text)


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


COMMANDS = {"PartReview_MeshAssistant": MeshAssistantCommand(),
            "PartReview_CheckMesh": CheckMeshCommand(),
            "PartReview_FemReport": FemReportCommand()}


def register():
    for name, command in COMMANDS.items():
        Gui.addCommand(name, command)
    return list(COMMANDS)
