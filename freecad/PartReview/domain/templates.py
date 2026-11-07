# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""User report templates (phase 6a, step g): company look and fixed texts.

Pure data + JSON-ready dicts. Files live in PartReview's own folder, never in
the original DFM add-on's folder (AUDITORIA.md, 8.5); see adapters/template_store.
All texts here are user texts: never translated.
"""

import re
from dataclasses import asdict, dataclass, fields

from .models import ReportConfig, ReportLevel, UnitSystem, SUPPORTED_LANGUAGES

FORMAT_VERSION = 1
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class ReportTemplate:
    name: str
    company: str = ""
    responsible: str = ""
    logo_path: str = ""
    accent_color: str = ""  # "#1f4a7d"; empty = default
    intro_text: str = ""
    disclaimer_text: str = ""
    level: str = ReportLevel.FULL.value
    language: str = "pt_BR"
    unit_system: str = UnitSystem.MPA_MM.value

    def validate(self) -> list[str]:
        errors = []
        if not self.name.strip():
            errors.append("template.error.name")
        if self.accent_color and not _HEX.match(self.accent_color):
            errors.append("template.error.color")
        if self.level not in {lv.value for lv in ReportLevel}:
            errors.append("template.error.level")
        if self.language not in SUPPORTED_LANGUAGES:
            errors.append("template.error.language")
        if self.unit_system not in {u.value for u in UnitSystem}:
            errors.append("template.error.units")
        return errors

    def to_dict(self) -> dict:
        data = asdict(self)
        data["format"] = FORMAT_VERSION
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "ReportTemplate":
        if not isinstance(data, dict):
            raise ValueError("template must be a JSON object")
        if data.get("format", FORMAT_VERSION) > FORMAT_VERSION:
            raise ValueError("template format %r is newer than supported" % data.get("format"))
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in data.items() if k in known}
        if not all(isinstance(v, str) for v in values.values()):
            raise ValueError("template values must be text")
        template = cls(**values)
        errors = template.validate()
        if errors:
            raise ValueError(", ".join(errors))
        return template

    def apply_to(self, config: ReportConfig) -> None:
        """Copy the template into the single report configuration (rule 2)."""
        config.company = self.company
        config.author = self.responsible
        config.logo_path = self.logo_path
        config.accent_color = self.accent_color
        config.intro_text = self.intro_text
        config.disclaimer_text = self.disclaimer_text
        config.level = ReportLevel(self.level)
        config.language = self.language
        config.unit_system = UnitSystem(self.unit_system)

    @classmethod
    def from_config(cls, name: str, config: ReportConfig) -> "ReportTemplate":
        return cls(name=name, company=config.company, responsible=config.author,
                   logo_path=config.logo_path, accent_color=config.accent_color,
                   intro_text=config.intro_text, disclaimer_text=config.disclaimer_text,
                   level=config.level.value, language=config.language,
                   unit_system=config.unit_system.value)


def file_stem(name: str) -> str:
    """Safe file name for a template name (letters, digits, '-', '_')."""
    stem = re.sub(r"[^\w\-]+", "_", name.strip(), flags=re.UNICODE).strip("_")
    return stem[:60] or "template"


def accent_rgb(color: str):
    """'#1f4a7d' -> (r, g, b) in 0..1, or None when empty/invalid."""
    if not color or not _HEX.match(color):
        return None
    return tuple(int(color[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
