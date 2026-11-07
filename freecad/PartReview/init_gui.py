# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import os

import FreeCADGui as Gui  # type: ignore

ICON_PATH = os.path.join(os.path.dirname(__file__), "resources", "icons", "partreview.svg")


class PartReviewWorkbench(Gui.Workbench):
    """PartReview workbench: professional reports of FEM results."""

    MenuText = "PartReview"
    ToolTip = "Professional reports of FreeCAD FEM results"
    Icon = ICON_PATH

    def Initialize(self):
        from .ui import commands

        names = commands.register()
        self.appendToolbar("PartReview", names)
        self.appendMenu("PartReview", names)

    def Activated(self):
        return

    def Deactivated(self):
        return

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(PartReviewWorkbench())
