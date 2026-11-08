# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Small user preferences kept by FreeCAD between sessions."""

import json
import os

import FreeCAD as App  # type: ignore

from ..domain.templates import ReportTemplate

PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/PartReview"
# FreeCAD's own logo, used as the default cover logo. Read from the installation
# (never copied into this repository); missing on some systems -> no default logo.
_FREECAD_LOGOS = ("pixmaps/freecad.svg", "icons/hicolor/scalable/apps/org.freecad.FreeCAD.svg")


def _params():
    return App.ParamGet(PARAM_PATH)


def freecad_logo_path() -> str:
    base = App.getResourceDir()
    for relative in _FREECAD_LOGOS:
        path = os.path.join(base, relative)
        if os.path.isfile(path):
            return path
    return ""


def last_report_fields():
    """(template with the fields of the last report, csv, html), or None the first time."""
    text = _params().GetString("LastReport", "")
    if not text:
        old_logo = _params().GetString("LastLogoPath", "")  # v1.4.0 kept only the logo
        if old_logo:
            return ReportTemplate(name="last", logo_path=old_logo), False, False
        return None
    try:
        data = json.loads(text)
        return (ReportTemplate.from_dict(data["fields"]), bool(data.get("csv")),
                bool(data.get("html")))
    except (ValueError, KeyError, TypeError) as err:
        App.Console.PrintWarning("PartReview: last report settings ignored (%s)\n" % err)
        return None


def remember_report_fields(config) -> None:
    """Called after a report is generated: company, author, logo, look, level, language,
    units and exports come back next time (title, result, output and yield do not)."""
    fields = ReportTemplate.from_config("last", config).to_dict()
    _params().SetString("LastReport", json.dumps(
        {"fields": fields, "csv": config.export_csv, "html": config.export_html}))
    _params().SetString("LastLogoPath", config.logo_path or "")
