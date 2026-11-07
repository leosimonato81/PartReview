# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Translation of the tool's OWN texts (CLAUDE.md rule 4).

User texts (title, notes, object labels) are never passed through here.
Dictionaries live in ``freecad/PartReview/locales/<language>.json``.
"""

import datetime
import json
from pathlib import Path

from .models import SUPPORTED_LANGUAGES, Vec3
from .units import Quantity, format_number, format_quantity

LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"
DECIMAL_SEPARATOR = {"pt_BR": ",", "en": "."}
LIST_SEPARATOR = {"pt_BR": "; ", "en": ", "}


def load_messages(language: str) -> dict:
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError("unsupported language %r" % language)
    with open(LOCALES_DIR / ("%s.json" % language), encoding="utf-8") as fh:
        return json.load(fh)


class Translator:
    """``t(key, **values)`` plus number/date formatting for one language.

    With ``strict=True`` a missing key raises KeyError (used by tests);
    otherwise the key itself is returned so a gap is visible but harmless.
    """

    def __init__(self, language: str, strict: bool = False):
        self.language = language
        self.strict = strict
        self._messages = load_messages(language)
        self.decimal_sep = DECIMAL_SEPARATOR[language]
        self.list_sep = LIST_SEPARATOR[language]

    def t(self, key: str, **values) -> str:
        if key not in self._messages:
            if self.strict:
                raise KeyError(key)
            return key
        return self._messages[key].format(**values)

    def has(self, key: str) -> bool:
        return key in self._messages

    def number(self, value: float, significant: int = 3) -> str:
        return format_number(value, significant, self.decimal_sep)

    def quantity(self, q: Quantity | None, significant: int = 3) -> str:
        return format_quantity(q, significant, self.decimal_sep) if q is not None else "—"

    def point(self, p: Vec3, unit: str, significant: int = 3) -> str:
        coords = self.list_sep.join(self.number(c, significant) for c in p)
        return "(%s) %s" % (coords, unit)

    def date(self, day: datetime.date) -> str:
        return day.strftime("%d/%m/%Y" if self.language == "pt_BR" else "%Y-%m-%d")
