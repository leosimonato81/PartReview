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
- The output FOLDER (owner's request, 2026-11-11): reports go to the user's
  Downloads folder; when the user saves a report elsewhere, that folder is
  remembered across sessions in the same file. The file name is never
  remembered (it comes from the document).
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


def _read() -> dict:
    """Contents of last_report.json ({} when missing or unreadable)."""
    path = _file()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
        if "fields" in data and "logo" not in data:  # file of v1.5: only its logo is used
            data = {"logo": ReportTemplate.from_dict(data["fields"]).logo_path}
        return data
    except (OSError, ValueError, KeyError, TypeError) as err:
        App.Console.PrintWarning("PartReview: remembered report settings ignored (%s): %s\n"
                                 % (path, err))
        return {}


def _write(data: dict) -> None:
    """Atomic write of last_report.json; removed when there is nothing to keep."""
    path = _file()
    try:
        if not data:
            if os.path.isfile(path):
                os.remove(path)
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except OSError as err:  # the report was generated; only this memory is lost
        App.Console.PrintWarning("PartReview: could not remember the report settings "
                                 "(%s): %s\n" % (path, err))


def remembered_logo():
    """Logo chosen by the user in an earlier session ("" = no logo), or None for
    the default (FreeCAD's logo)."""
    data = _read()
    if "logo" not in data:
        return None
    logo = str(data["logo"])
    return None if logo == freecad_logo_path() else logo


def downloads_dir() -> str:
    """The user's Downloads folder as the system names it (Windows, Linux in any
    language, macOS); the home folder when the system has none."""
    try:
        from PySide6.QtCore import QStandardPaths  # GUI side only; imported here on purpose
        path = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
    except ImportError:
        path = ""
    if path and os.path.isdir(path):
        return path
    return os.path.expanduser("~")


def output_dir() -> str:
    """Folder for a new report: the one the user last chose, if it still exists,
    else the Downloads folder."""
    folder = str(_read().get("output_dir") or "")
    return folder if folder and os.path.isdir(folder) else downloads_dir()


def remember_report_fields(config) -> None:
    """Called after a report is generated: keeps the fields for this session and
    writes to disk, at once, what is remembered across sessions: the logo when it
    differs from the default and the output folder when it differs from Downloads
    (back to a default: the entry is removed). Title, result and file name are
    never remembered."""
    global _session
    _session = (ReportTemplate.from_config("last", config), config.export_csv,
                config.export_html, config.show_boundary, config.yield_strength,
                config.required_safety)
    data = {}
    if config.logo_path != freecad_logo_path():
        data["logo"] = config.logo_path
    folder = os.path.dirname(os.path.abspath(config.output_path)) if config.output_path else ""
    if folder and os.path.normcase(folder) != os.path.normcase(downloads_dir()):
        data["output_dir"] = folder
    if data != _read():
        _write(data)
