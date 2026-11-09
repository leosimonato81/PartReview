# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""What the report dialog remembers (owner's rules, 2026-11-08).

- The fields of the last report (company, author, look, level, language, units,
  exports, supports/loads figure, yield strength, required safety factor) are
  remembered only while FreeCAD stays open: kept in memory, forgotten when
  FreeCAD closes.
- The logo is the exception: when the user changes it from the default
  (FreeCAD's logo), including to no logo, it is remembered across sessions,
  in PartReview's own file written at once (never in FreeCAD's user.cfg, which
  is written only when FreeCAD closes and the last window to close wins).
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


# The same logo is compiled into FreeCAD's GUI (Qt resource) on every system
# (Linux, Windows, macOS, AppImage, Flatpak...): copied once to our own folder
# when the installation has no loose file.
_FREECAD_LOGO_RESOURCE = ":/icons/freecad.svg"


def freecad_logo_path() -> str:
    """FreeCAD's own logo as a file path ("" only if FreeCAD has none at all)."""
    base = App.getResourceDir()
    for relative in _FREECAD_LOGOS:
        path = os.path.join(base, relative)
        if os.path.isfile(path):
            return path
    copy = os.path.join(App.getUserAppDataDir(), "PartReview", "freecad_logo.svg")
    if os.path.isfile(copy):
        return copy
    try:
        from PySide6.QtCore import QFile  # GUI side only; imported here on purpose
        resource = QFile(_FREECAD_LOGO_RESOURCE)
        if not resource.open(QFile.ReadOnly):
            return ""
        data = bytes(resource.readAll())
        resource.close()
        os.makedirs(os.path.dirname(copy), exist_ok=True)
        tmp = copy + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, copy)
        return copy
    except (ImportError, OSError) as err:
        App.Console.PrintWarning("PartReview: FreeCAD logo not available (%s)\n" % err)
        return ""


# Fields of the last report in this FreeCAD session (module memory: gone on exit).
_session = None


def last_report_fields():
    """(template with the fields of the last report, csv, html, boundary, yield
    strength, required safety factor) of this FreeCAD session, or None when no
    report was made yet."""
    return _session


def remembered_logo():
    """Logo chosen by the user in an earlier session ("" = no logo), or None for
    the default (FreeCAD's logo)."""
    path = _file()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if "logo" in data:
            logo = str(data["logo"])
        else:  # file of v1.5 (all fields): only its logo is still used
            logo = ReportTemplate.from_dict(data["fields"]).logo_path
    except (OSError, ValueError, KeyError, TypeError) as err:
        App.Console.PrintWarning("PartReview: remembered logo ignored (%s): %s\n"
                                 % (path, err))
        return None
    return None if logo == freecad_logo_path() else logo


def remember_report_fields(config) -> None:
    """Called after a report is generated: keeps the fields for this session and,
    when the logo differs from the default, writes it to disk atomically, at once
    (back to the default: the file is removed). Title, result and output are
    never remembered."""
    global _session
    _session = (ReportTemplate.from_config("last", config), config.export_csv,
                config.export_html, config.show_boundary, config.yield_strength,
                config.required_safety)
    path = _file()
    try:
        if config.logo_path == freecad_logo_path():
            if os.path.isfile(path):
                os.remove(path)
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"logo": config.logo_path}, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except OSError as err:  # report was generated; only the memory of the logo is lost
        App.Console.PrintWarning("PartReview: could not remember the logo (%s): %s\n"
                                 % (path, err))
