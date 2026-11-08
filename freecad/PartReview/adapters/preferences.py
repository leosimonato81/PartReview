# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""What the report dialog remembers between sessions.

Kept in PartReview's own file, written at once when a report is generated, and
NOT in FreeCAD's user.cfg: FreeCAD writes user.cfg only when it closes, as a
whole copy of what it holds in memory, so another FreeCAD window (or a crash)
could overwrite or lose the remembered fields.
"""

import json
import os

import FreeCAD as App  # type: ignore

from ..domain.templates import ReportTemplate

# FreeCAD's own logo, used as the default cover logo the first time. Read from the
# installation (never copied into this repository); missing on some systems.
_FREECAD_LOGOS = ("pixmaps/freecad.svg", "icons/hicolor/scalable/apps/org.freecad.FreeCAD.svg")


def _file():
    return os.path.join(App.getUserAppDataDir(), "PartReview", "last_report.json")


def freecad_logo_path() -> str:
    base = App.getResourceDir()
    for relative in _FREECAD_LOGOS:
        path = os.path.join(base, relative)
        if os.path.isfile(path):
            return path
    return ""


def last_report_fields():
    """(template with the fields of the last report, csv, html), or None the first time."""
    path = _file()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return (ReportTemplate.from_dict(data["fields"]), bool(data.get("csv")),
                bool(data.get("html")))
    except (OSError, ValueError, KeyError, TypeError) as err:
        App.Console.PrintWarning("PartReview: last report settings ignored (%s): %s\n"
                                 % (path, err))
        return None


def remember_report_fields(config) -> None:
    """Called after a report is generated: company, author, logo (also an empty one),
    look, level, language, units and exports come back next time (title, result,
    output and yield do not). Written atomically, right away."""
    path = _file()
    data = {"fields": ReportTemplate.from_config("last", config).to_dict(),
            "csv": config.export_csv, "html": config.export_html}
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except OSError as err:  # report was generated; only the memory of fields is lost
        App.Console.PrintWarning("PartReview: could not remember the report fields (%s): %s\n"
                                 % (path, err))
