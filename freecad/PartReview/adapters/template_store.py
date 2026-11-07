# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Report templates on disk, in PartReview's own folder (AUDITORIA.md 8.5).

<FreeCAD user data>/PartReview/templates/<name>.json - never the original
DFM add-on's DFM/report_templates folder.
"""

import json
import os

import FreeCAD as App  # type: ignore

from ..domain.templates import ReportTemplate, file_stem


def templates_dir():
    return os.path.join(App.getUserAppDataDir(), "PartReview", "templates")


def _path(name):
    return os.path.join(templates_dir(), file_stem(name) + ".json")


def list_templates():
    """Valid templates sorted by name; unreadable files are reported, not hidden."""
    folder = templates_dir()
    if not os.path.isdir(folder):
        return []
    found = []
    for entry in sorted(os.listdir(folder)):
        if not entry.endswith(".json"):
            continue
        path = os.path.join(folder, entry)
        try:
            with open(path, encoding="utf-8") as fh:
                found.append(ReportTemplate.from_dict(json.load(fh)))
        except (OSError, ValueError) as err:  # json.JSONDecodeError is a ValueError
            App.Console.PrintWarning("PartReview: template %s ignored: %s\n" % (path, err))
    return sorted(found, key=lambda t: t.name.lower())


def save_template(template):
    """Write atomically; returns the file path. Raises ValueError if invalid."""
    errors = template.validate()
    if errors:
        raise ValueError(errors[0])
    os.makedirs(templates_dir(), exist_ok=True)
    path = _path(template.name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(template.to_dict(), fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def delete_template(name):
    path = _path(name)
    if os.path.isfile(path):
        os.remove(path)
