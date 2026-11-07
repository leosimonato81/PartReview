# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Pluggable report sections (decision 003).

A section knows its key, position, the report levels it belongs to, whether
it applies to the current data and how to build its blocks. The engine knows
nothing about FEM or DFM: new sections (DFM in phase 4, combined risks in
phase 5) are just new ``Section`` objects registered here.
"""

from dataclasses import dataclass
from typing import Callable

from .blocks import Heading, TocEntry
from .models import ReportLevel

ALL_LEVELS = frozenset(ReportLevel)
DETAILED_LEVELS = frozenset({ReportLevel.STANDARD, ReportLevel.FULL})


def _always(ctx) -> bool:
    return True


@dataclass(frozen=True)
class Section:
    key: str  # stable id, e.g. "fem.results"
    order: int  # position in the report (lower first)
    title_key: str  # i18n key of the section title
    levels: frozenset  # ReportLevel members where the section appears
    build: Callable  # (ctx, translator, level) -> list of blocks
    applies: Callable = _always  # (ctx) -> bool


class SectionRegistry:
    def __init__(self, sections=()):
        self._sections = {}
        for section in sections:
            self.register(section)

    def register(self, section: Section) -> None:
        if section.key in self._sections:
            raise ValueError("section %r registered twice" % section.key)
        self._sections[section.key] = section

    def __iter__(self):
        return iter(sorted(self._sections.values(), key=lambda s: (s.order, s.key)))

    def __len__(self):
        return len(self._sections)


def compose(ctx, tr, registry: SectionRegistry, level: ReportLevel):
    """Blocks and table of contents for ``level``, numbering sections in order.

    Sections that do not apply, or build nothing, are skipped without leaving
    a gap in the numbering.
    """
    blocks, toc = [], []
    for section in registry:
        if level not in section.levels or not section.applies(ctx):
            continue
        content = section.build(ctx, tr, level)
        if not content:
            continue
        number = len(toc) + 1
        title = tr.t(section.title_key)
        toc.append(TocEntry(number, title, section.key))
        blocks.append(Heading("%d. %s" % (number, title), anchor=section.key))
        blocks.extend(content)
    return blocks, toc
