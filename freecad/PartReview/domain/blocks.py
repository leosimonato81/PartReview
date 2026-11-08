# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Building blocks of a report document (what to show, not how to draw it).

Renderers (PDF, HTML) only draw these. They carry final, already translated
text; user texts are copied as typed.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Heading:
    text: str
    anchor: str = ""  # stable id (section key), used by the table of contents


@dataclass(frozen=True)
class Paragraph:
    text: str


@dataclass(frozen=True)
class BulletList:
    items: tuple[str, ...]


@dataclass(frozen=True)
class Notice:
    text: str
    level: str = "warning"  # "warning" or "info"


@dataclass(frozen=True)
class Table:
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    widths: tuple[float, ...]  # column width fractions, sum 1


@dataclass(frozen=True)
class Legend:
    title: str
    ticks: tuple[tuple[float, str], ...]  # (position 0 = min .. 1 = max, label)
    # Category legend instead of a color bar: ((r, g, b) 0..255, label) per entry.
    swatches: tuple[tuple[tuple[int, int, int], str], ...] = ()


@dataclass(frozen=True)
class Marker:
    number: int
    u: float  # pixel position in the captured image (first leader)
    v: float
    style: str = "result"  # "result" (black), "load" (orange) or "support" (purple)
    more: tuple[tuple[float, float], ...] = ()  # extra leaders: other faces/edges


@dataclass(frozen=True)
class Figure:
    view_index: int  # index into the captured images
    caption: str
    legend: Legend
    markers: tuple[Marker, ...]
    image_size: tuple[int, int]
    balloons: str = ""  # what each numbered balloon in this figure is


@dataclass(frozen=True)
class BarChart:
    title: str
    labels: tuple[str, ...]  # one per bar
    values: tuple[float, ...]
    caption: str = ""
    x_title: str = ""
    y_title: str = ""


@dataclass(frozen=True)
class TocEntry:
    number: int
    title: str  # without the number
    anchor: str


@dataclass(frozen=True)
class Cover:
    title: str  # user title, or the default report title
    subtitle: str  # kind of report (translated); empty when it equals the title
    info: tuple[tuple[str, str], ...]  # (label, value) rows
    company: str = ""  # user text
    logo_path: str = ""
    level_label: str = ""  # e.g. "Completo"
    level_caption: str = ""  # e.g. "Nível do relatório"
    full_page: bool = True  # False: compact header on the first content page


DEFAULT_ACCENT_HEX = "#000000"  # black (owner's choice, v1.4.0); templates may override
DEFAULT_ACCENT = (0.0, 0.0, 0.0)  # same color as DEFAULT_ACCENT_HEX, in 0..1


@dataclass(frozen=True)
class Document:
    cover: Cover
    blocks: tuple = field(repr=False)
    toc: tuple[TocEntry, ...] = ()
    toc_title: str = ""  # translated "Contents"; the TOC is drawn only when toc is set
    header_text: str = ""  # running header on content pages
    footer: str = ""
    page_template: str = "{page} / {pages}"
    accent: tuple[float, float, float] = DEFAULT_ACCENT
    author: str = ""

    @property
    def title(self) -> str:
        return self.cover.title
