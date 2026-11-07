# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Traceability data of a report (phase 6a, step e): what, from where, with what."""

import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class Traceability:
    tool_version: str
    freecad_version: str  # e.g. "1.1.4 (build 45039, commit 4fd3bf32)"
    generated_at: datetime.datetime
    platform: str
    python_version: str
    file_name: str
    file_path: str
    file_sha256: str  # "" when the document was never saved
    file_modified: datetime.datetime | None
    unsaved_changes: bool  # the hash is of the saved file, not of the open document
    result_name: str
    result_label: str
    solver: str
    analysis_type: str
    # Raw FreeCAD property values (enumerations such as "linear"), not translated.
    solver_settings: tuple[tuple[str, str], ...] = ()
    mesher: str = ""
    mesher_settings: tuple[tuple[str, str], ...] = ()

    def setting(self, name: str) -> str:
        return dict(self.solver_settings).get(name, "")

    @property
    def short_hash(self) -> str:
        return self.file_sha256[:12]
