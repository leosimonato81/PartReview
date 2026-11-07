# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Small user preferences kept by FreeCAD between sessions."""

import FreeCAD as App  # type: ignore

PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/PartReview"


def _params():
    return App.ParamGet(PARAM_PATH)


def last_logo_path() -> str:
    """Logo used in the last report generated (empty when none)."""
    return _params().GetString("LastLogoPath", "")


def remember_logo_path(path: str) -> None:
    """Called after a report is generated, also with "" when it had no logo."""
    _params().SetString("LastLogoPath", path or "")
