# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Draw a domain Document into a PDF with Qt (QPdfWriter, ships with FreeCAD).

Layout only: every text arrives already translated in the Document blocks.
Two passes: blocks are first laid out into pages (so "page x of y" and the
page of each section are known), then painted.

Text stays searchable and copyable: the font is embedded with a Unicode map,
and typographic ligatures are switched off, because with them "fi"/"fl" are
extracted as the single characters U+FB01/U+FB02 and a search for "finite"
fails (AUDITORIA.md B16; verified with pdftotext, 2026-11-07).
"""

from PySide6.QtCore import QMarginsF, QPointF, QRectF, Qt  # type: ignore
from PySide6.QtGui import (  # type: ignore
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QLinearGradient,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPen,
)

from .. import __version__
from ..domain import colormap
from ..domain.colors import accent_palette
from ..domain.logo import COMPACT_COVER_BOX_MM, FULL_COVER_BOX_MM
from ..domain.blocks import BarChart, BulletList, Figure, Heading, Notice, Paragraph, Table
from ..domain.balloons import place_balloon
from .logo_loader import load_logo

DPI = 300
MARGIN_MM = 18.0
HEADER_MM = 8.0  # running header band inside the top margin
FOOTER_MM = 10.0
LEGEND_MM = 30.0
GAP_MM = 3.0

INK = QColor(30, 30, 30)
MUTED = QColor(110, 110, 110)
RULE = QColor(200, 200, 200)
WARNING = QColor(214, 130, 0)
INFO = QColor(40, 110, 190)
FONT_FAMILY = "Sans Serif"


def mm(value):
    return value * DPI / 25.4


def make_font(size, bold=False, italic=False):
    font = QFont(FONT_FAMILY)
    font.setPointSizeF(size)
    font.setBold(bold)
    font.setItalic(italic)
    font.setFeature(QFont.Tag("liga"), 0)  # keep "fi"/"fl" as plain letters (B16)
    return font


class _Style:
    """One place for typography and colors, so every page looks the same."""

    def __init__(self, device, accent):
        self.device = device
        # WCAG-checked shades of the user's color (domain/colors.py): titles >= 4.5:1,
        # rules and chart bars >= 3:1; the decorative cover band keeps the exact color.
        palette = accent_palette(accent)
        self.accent_band = QColor.fromRgbF(*palette.base)
        self.accent = QColor.fromRgbF(*palette.graphic)
        self.accent_text = QColor.fromRgbF(*palette.text)
        self.accent_light = QColor.fromRgbF(*palette.light)
        self.cover_title = make_font(26, bold=True)
        self.cover_subtitle = make_font(13)
        self.title = make_font(18, bold=True)
        self.heading = make_font(12.5, bold=True)
        self.body = make_font(9.5)
        self.bold = make_font(9.5, bold=True)
        self.small = make_font(8)
        self.caption = make_font(8.5, italic=True)

    def height(self, font, text, width):
        fm = QFontMetricsF(font, self.device)
        return fm.boundingRect(QRectF(0, 0, width, 1e6), int(Qt.TextWordWrap), text).height()


class _Layout:
    """Places drawing operations on pages, breaking pages when needed."""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.top = mm(MARGIN_MM)
        self.bottom = height - mm(MARGIN_MM) - mm(FOOTER_MM)
        self.pages = [[]]
        self.y = self.top
        self.anchor_pages = {}  # section anchor -> page number (for the contents)
        self.cover_pages = 0  # pages without running header/footer
        self.title_on_first_page = False  # compact cover: page 1 has no running header

    def new_page(self):
        self.pages.append([])
        self.y = self.top

    def ensure(self, needed):
        if self.y + needed > self.bottom and self.y > self.top:
            self.new_page()

    def add(self, op):
        self.pages[-1].append(op)


def _text_op(font, text, rect, color=INK, flags=None):
    flags = int(Qt.TextWordWrap) if flags is None else flags

    def op(p):
        p.setFont(font)
        p.setPen(color)
        p.drawText(rect, flags, text)
    return op


def _fill_op(rect, color):
    def op(p):
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRect(rect)
    return op


def _line_op(x1, y1, x2, y2, color, width_mm):
    def op(p):
        p.setPen(QPen(color, mm(width_mm)))
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    return op


# Balloon colors outside the result color map (blue-cyan-green-yellow-red):
# results black (white balloon), loads dark orange and supports purple (filled
# balloons, white number). Tips are white with a colored border, so they stand out
# on any color of the map: round for results and loads, square for supports.
MARKER_COLORS = {"result": QColor(20, 20, 20), "load": QColor(230, 81, 0),
                 "support": QColor(106, 27, 154)}
_DRAW_ORDER = {"result": 0, "load": 1, "support": 2}


def _background_test(image):
    """is_background(x, y) for a capture made on a white background."""
    width, height = image.width(), image.height()

    def is_background(x, y):
        xi, yi = int(x), int(y)
        if not (0 <= xi < width and 0 <= yi < height):
            return False
        c = image.pixel(xi, yi)
        return min((c >> 16) & 255, (c >> 8) & 255, c & 255) >= 235

    return is_background


def _part_center(image, is_background, step=8):
    xs = ys = n = 0
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            if not is_background(x, y):
                xs, ys, n = xs + x, ys + y, n + 1
    return (xs / n, ys / n) if n else None


def draw_markers(image, markers):
    """Numbered balloons on a copy of the captured image: one balloon per visible
    face/edge (same number), placed on the background next to its tip."""
    out = image.copy()
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    radius = max(14.0, image.width() / 60.0)
    font = QFont(FONT_FAMILY)
    font.setPixelSize(int(radius * 1.1))
    font.setBold(True)
    p.setFont(font)
    is_background = _background_test(image)
    center_of_part = _part_center(image, is_background)
    callouts = []  # (style, number, tip, balloon center)
    placed = []
    for m in sorted(markers, key=lambda m: _DRAW_ORDER.get(m.style, 0)):
        for tip in ((m.u, m.v),) + tuple(m.more):
            c = place_balloon(tip, radius, (image.width(), image.height()), is_background,
                              placed, center_of_part)
            placed.append(c)
            callouts.append((m.style, m.number, tip, c))
    for style, number, (u, v), (cx, cy) in callouts:  # leaders first, balloons on top
        color = MARKER_COLORS.get(style, MARKER_COLORS["result"])
        target, center = QPointF(u, v), QPointF(cx, cy)
        p.setPen(QPen(QColor(255, 255, 255), radius / 6 + 3))  # white halo: readable
        p.drawLine(target, center)                              # on any color map
        p.setPen(QPen(color, radius / 6))
        p.drawLine(target, center)
        if style == "result":
            p.setPen(QPen(QColor(255, 255, 255), 2))
            p.setBrush(color)
            p.drawEllipse(target, radius / 3.4, radius / 3.4)
        else:
            p.setPen(QPen(color, radius / 5))
            p.setBrush(QColor(255, 255, 255))
            if style == "support":
                s = radius / 3.0
                p.drawRect(QRectF(u - s, v - s, 2 * s, 2 * s))
            else:
                p.drawEllipse(target, radius / 3.0, radius / 3.0)
    for style, number, _, (cx, cy) in callouts:
        color = MARKER_COLORS.get(style, MARKER_COLORS["result"])
        filled = style != "result"
        p.setPen(QPen(color, radius / 5))
        p.setBrush(color if filled else QColor(255, 255, 255))
        p.drawEllipse(QPointF(cx, cy), radius, radius)
        p.setPen(QColor(255, 255, 255) if filled else color)
        p.drawText(QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius),
                   int(Qt.AlignCenter), str(number))
    p.end()
    return out


def _legend_op(legend, x, y, height, style):
    def op(p):
        bar_w = mm(5)
        title_h = style.height(style.small, legend.title, mm(LEGEND_MM - 2))
        p.setFont(style.small)
        p.setPen(INK)
        p.drawText(QRectF(x, y, mm(LEGEND_MM - 2), title_h), int(Qt.TextWordWrap), legend.title)
        top = y + title_h + mm(3)
        bar_h = max(mm(20), height - title_h - mm(8))
        grad = QLinearGradient(0, top + bar_h, 0, top)  # bottom = min, top = max
        for pos, (r, g, b) in colormap.STOPS:
            grad.setColorAt(pos, QColor.fromRgbF(r, g, b))
        p.setPen(QPen(MUTED, mm(0.2)))
        p.setBrush(grad)
        p.drawRect(QRectF(x, top, bar_w, bar_h))
        fm = QFontMetricsF(style.small, p.device())
        for pos, label in legend.ticks:
            ty = top + bar_h * (1 - pos)
            p.drawLine(QPointF(x + bar_w, ty), QPointF(x + bar_w + mm(1.5), ty))
            p.drawText(QPointF(x + bar_w + mm(2.5), ty + fm.ascent() / 2.5), label)
    return op


def _layout_table(layout, table, x0, style):
    width = layout.width
    widths = [w * width for w in table.widths]
    pad = mm(1.5)

    def row_height(cells, font):
        return max(style.height(font, c, w - 2 * pad) for c, w in zip(cells, widths)) + 2 * pad

    def place_row(cells, font, fill):
        h = row_height(cells, font)
        layout.ensure(h)
        y = layout.y
        if fill is not None:
            layout.add(_fill_op(QRectF(x0, y, width, h), fill))
        x = x0
        for cell, w in zip(cells, widths):
            layout.add(_text_op(font, cell, QRectF(x + pad, y + pad, w - 2 * pad, h)))
            x += w
        layout.add(_line_op(x0, y + h, x0 + width, y + h, RULE, 0.2))
        layout.y += h

    if table.header:
        place_row(table.header, style.bold, style.accent_light)
    for row in table.rows:
        place_row(row, style.body, None)
    layout.y += mm(GAP_MM)


def _layout_bar_chart(layout, chart, x0, style):
    """Simple vertical bar chart with value labels, axes and caption."""
    width = layout.width
    title_h = style.height(style.bold, chart.title, width)
    cap_h = style.height(style.caption, chart.caption, width) if chart.caption else 0
    plot_h = mm(55)
    label_h = style.height(style.small, "Ag", width) * 2.2
    total = title_h + mm(2) + plot_h + label_h + cap_h + mm(4)
    layout.ensure(total)
    y = layout.y
    layout.add(_text_op(style.bold, chart.title, QRectF(x0, y, width, title_h)))
    top = y + title_h + mm(4)
    left = x0 + mm(14)
    plot_w = width - mm(16)
    peak = max(chart.values) if chart.values and max(chart.values) > 0 else 1.0
    n = max(1, len(chart.values))
    slot = plot_w / n

    def op(p):
        p.setPen(QPen(MUTED, mm(0.25)))
        p.drawLine(QPointF(left, top + plot_h), QPointF(left + plot_w, top + plot_h))
        p.drawLine(QPointF(left, top), QPointF(left, top + plot_h))
        fm = QFontMetricsF(style.small, p.device())
        p.setFont(style.small)
        for i, (label, value) in enumerate(zip(chart.labels, chart.values)):
            bar_h = plot_h * value / peak
            bx = left + i * slot + slot * 0.15
            p.setPen(Qt.NoPen)
            p.setBrush(style.accent)
            p.drawRect(QRectF(bx, top + plot_h - bar_h, slot * 0.7, bar_h))
            p.setPen(INK)
            text = "%d" % value
            p.drawText(QPointF(bx + slot * 0.35 - fm.horizontalAdvance(text) / 2,
                               top + plot_h - bar_h - mm(1)), text)
            p.setPen(MUTED)
            p.drawText(QRectF(left + i * slot, top + plot_h + mm(1), slot, label_h),
                       int(Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap), label)
        p.save()
        p.translate(x0 + mm(4), top + plot_h / 2)
        p.rotate(-90)
        p.drawText(QRectF(-plot_h / 2, -mm(4), plot_h, mm(5)), int(Qt.AlignCenter), chart.y_title)
        p.restore()
    layout.add(op)
    y_axis_title = top + plot_h + label_h
    if chart.x_title:
        layout.add(_text_op(style.small, chart.x_title, QRectF(left, y_axis_title, plot_w, mm(4)),
                            MUTED, int(Qt.AlignHCenter)))
    if chart.caption:
        layout.add(_text_op(style.caption, chart.caption,
                            QRectF(x0, y_axis_title + mm(5), width, cap_h), MUTED))
    layout.y = y_axis_title + mm(5) + cap_h + mm(4)


def _layout_full_cover(layout, cover, x0, style):
    """Dedicated cover page: accent band, company, title, info table, logo at the bottom."""
    width = layout.width
    layout.add(_fill_op(QRectF(0, 0, x0 * 2 + width, mm(12)), style.accent_band))
    top = mm(24)
    logo = load_logo(cover.logo_path, FULL_COVER_BOX_MM)
    if logo is not None:
        box_w, box_h = mm(FULL_COVER_BOX_MM[0]), mm(FULL_COVER_BOX_MM[1])
        scale = min(box_w / logo.width(), box_h / logo.height())
        w, h = logo.width() * scale, logo.height() * scale
        # Centered at the bottom of the cover (owner's choice, v1.4.0).
        rect = QRectF(x0 + (width - w) / 2, layout.height - mm(MARGIN_MM) - h, w, h)
        layout.add(lambda p, r=rect, im=logo: p.drawImage(r, im))
    if cover.company:
        layout.add(_text_op(style.heading, cover.company, QRectF(x0, top, width, mm(22)),
                            INK, int(Qt.AlignRight | Qt.AlignTop | Qt.TextWordWrap)))
    y = mm(95)
    h = style.height(style.cover_title, cover.title, width)
    layout.add(_text_op(style.cover_title, cover.title, QRectF(x0, y, width, h),
                        style.accent_text))
    y += h + mm(3)
    if cover.subtitle:
        h = style.height(style.cover_subtitle, cover.subtitle, width)
        layout.add(_text_op(style.cover_subtitle, cover.subtitle, QRectF(x0, y, width, h), MUTED))
        y += h
    layout.add(_line_op(x0, y + mm(4), x0 + mm(40), y + mm(4), style.accent, 1.2))
    y = mm(170)
    rows = list(cover.info)
    if cover.level_label:
        rows.append((cover.level_caption, cover.level_label))
    label_w = mm(45)
    for label, value in rows:
        h = max(style.height(style.bold, label, label_w),
                style.height(style.body, value, width - label_w))
        layout.add(_text_op(style.bold, label, QRectF(x0, y, label_w, h), MUTED))
        layout.add(_text_op(style.body, value, QRectF(x0 + label_w, y, width - label_w, h)))
        y += h + mm(2.5)
    layout.cover_pages = 1
    layout.new_page()


def _layout_compact_cover(layout, cover, x0, style):
    """First-page title block for the quick summary (no separate cover page)."""
    width = layout.width
    logo = load_logo(cover.logo_path, COMPACT_COVER_BOX_MM)
    title_x = x0
    if logo is not None:
        box_w, box_h = mm(COMPACT_COVER_BOX_MM[0]), mm(COMPACT_COVER_BOX_MM[1])
        scale = min(box_w / logo.width(), box_h / logo.height())
        rect = QRectF(x0 + width - logo.width() * scale, layout.y,
                      logo.width() * scale, logo.height() * scale)
        layout.add(lambda p, r=rect, im=logo: p.drawImage(r, im))
    text_w = width - (mm(32) if logo is not None else 0)
    h = style.height(style.title, cover.title, text_w)
    layout.add(_text_op(style.title, cover.title, QRectF(title_x, layout.y, text_w, h),
                        style.accent_text))
    layout.y += h + mm(1.5)
    lines = [cover.subtitle] if cover.subtitle else []
    lines += ["%s: %s" % (k, v) for k, v in cover.info]
    if cover.company:
        lines.append(cover.company)
    if cover.level_label:
        lines.append("%s: %s" % (cover.level_caption, cover.level_label))
    for text in lines:
        h = style.height(style.body, text, text_w)
        layout.add(_text_op(style.body, text, QRectF(title_x, layout.y, text_w, h), MUTED))
        layout.y += h
    y_rule = layout.y + mm(2)
    layout.add(_line_op(x0, y_rule, x0 + width, y_rule, style.accent, 0.5))
    layout.y = y_rule + mm(5)
    layout.title_on_first_page = True


def _layout_toc(layout, doc, x0, style):
    """Contents page. Page numbers are read at paint time, when all are known."""
    width = layout.width
    h = style.height(style.title, doc.toc_title, width)
    layout.add(_text_op(style.title, doc.toc_title, QRectF(x0, layout.y, width, h),
                        style.accent_text))
    layout.y += h + mm(6)
    pages = layout.anchor_pages  # filled while the rest of the document is laid out
    row_h = style.height(style.body, "Ag", width) + mm(2.5)
    for entry in doc.toc:
        layout.ensure(row_h)
        y = layout.y

        def op(p, e=entry, yy=y):
            fm = QFontMetricsF(style.body, p.device())
            label = "%d.  %s" % (e.number, e.title)
            number = str(pages.get(e.anchor, ""))
            p.setFont(style.body)
            p.setPen(INK)
            p.drawText(QPointF(x0, yy + fm.ascent()), label)
            num_w = fm.horizontalAdvance(number)
            p.drawText(QPointF(x0 + width - num_w, yy + fm.ascent()), number)
            start = x0 + fm.horizontalAdvance(label) + mm(2)
            end = x0 + width - num_w - mm(2)
            p.setPen(QPen(RULE, mm(0.3), Qt.DotLine))
            if end > start:
                base = yy + fm.ascent()
                p.drawLine(QPointF(start, base), QPointF(end, base))
        layout.add(op)
        layout.y += row_h
    layout.new_page()


def layout_document(doc, image_paths, style, page_w, page_h):
    x0 = mm(MARGIN_MM)
    layout = _Layout(page_w - 2 * x0, page_h)
    if doc.cover.full_page:
        _layout_full_cover(layout, doc.cover, x0, style)
    else:
        _layout_compact_cover(layout, doc.cover, x0, style)
    if doc.toc:
        _layout_toc(layout, doc, x0, style)

    def figure_text(fig):
        return fig.caption + ("\n" + fig.balloons if fig.balloons else "")

    def figure_height(fig):
        img_h = (layout.width - mm(LEGEND_MM)) * fig.image_size[1] / fig.image_size[0]
        return img_h + style.height(style.caption, figure_text(fig), layout.width) + mm(2)

    blocks = list(doc.blocks)
    for index, block in enumerate(blocks):
        if isinstance(block, Heading):
            h = style.height(style.heading, block.text, layout.width)
            following = blocks[index + 1] if index + 1 < len(blocks) else None
            keep = figure_height(following) if isinstance(following, Figure) else mm(25)
            layout.ensure(h + mm(4) + keep)  # never leave a heading alone at a page end
            layout.y += mm(2)
            if block.anchor:
                layout.anchor_pages[block.anchor] = len(layout.pages)
            layout.add(_text_op(style.heading, block.text,
                                QRectF(x0, layout.y, layout.width, h), style.accent_text))
            layout.y += h + mm(2)
        elif isinstance(block, Paragraph):
            h = style.height(style.body, block.text, layout.width)
            layout.ensure(h)
            layout.add(_text_op(style.body, block.text, QRectF(x0, layout.y, layout.width, h)))
            layout.y += h + mm(GAP_MM)
        elif isinstance(block, BulletList):
            indent = mm(5)
            for item in block.items:
                h = style.height(style.body, item, layout.width - indent)
                layout.ensure(h)
                layout.add(_text_op(style.body, "•", QRectF(x0 + mm(1), layout.y, indent, h)))
                layout.add(_text_op(style.body, item,
                                    QRectF(x0 + indent, layout.y, layout.width - indent, h)))
                layout.y += h + mm(1.2)
            layout.y += mm(GAP_MM - 1.2)
        elif isinstance(block, Notice):
            color = WARNING if block.level == "warning" else INFO
            inner = layout.width - mm(5)
            h = style.height(style.body, block.text, inner) + mm(3)
            layout.ensure(h)
            y = layout.y
            layout.add(_fill_op(QRectF(x0, y, mm(1.2), h), color))
            layout.add(_text_op(style.body, block.text,
                                QRectF(x0 + mm(4), y + mm(1.5), inner, h)))
            layout.y += h + mm(2)
        elif isinstance(block, Table):
            _layout_table(layout, block, x0, style)
        elif isinstance(block, BarChart):
            _layout_bar_chart(layout, block, x0, style)
        elif isinstance(block, Figure):
            img_w = layout.width - mm(LEGEND_MM)
            iw, ih = block.image_size
            img_h = img_w * ih / iw
            cap_h = style.height(style.caption, figure_text(block), layout.width)
            layout.ensure(img_h + cap_h + mm(2))
            y = layout.y
            image = draw_markers(QImage(image_paths[block.view_index]), block.markers)
            rect = QRectF(x0, y, img_w, img_h)
            layout.add(lambda p, r=rect, im=image: (p.drawImage(r, im),
                                                    p.setPen(QPen(RULE, mm(0.2))),
                                                    p.setBrush(Qt.NoBrush), p.drawRect(r)))
            layout.add(_legend_op(block.legend, x0 + img_w + mm(4), y + mm(4),
                                  img_h - mm(8), style))
            layout.add(_text_op(style.caption, figure_text(block),
                                QRectF(x0, y + img_h + mm(1.5), layout.width, cap_h), MUTED))
            layout.y += img_h + cap_h + mm(6)
    return layout


def _paint_header_footer(painter, doc, style, page_number, total, page_w, page_h,
                         header=True):
    x0 = mm(MARGIN_MM)
    width = page_w - 2 * x0
    if header:
        _paint_header(painter, doc, style, x0, width)
    foot = QRectF(x0, page_h - mm(MARGIN_MM), width, mm(FOOTER_MM))
    painter.setFont(style.small)
    painter.setPen(MUTED)
    painter.drawText(foot, int(Qt.AlignLeft), doc.footer)
    painter.drawText(foot, int(Qt.AlignRight),
                     doc.page_template.format(page=page_number, pages=total))


def _paint_header(painter, doc, style, x0, width):
    band = QRectF(x0, mm(MARGIN_MM) - mm(HEADER_MM) - mm(2), width, mm(HEADER_MM))
    painter.setFont(style.small)
    painter.setPen(MUTED)
    painter.drawText(band, int(Qt.AlignLeft | Qt.AlignBottom), doc.header_text)
    if doc.cover.company:
        painter.drawText(band, int(Qt.AlignRight | Qt.AlignBottom), doc.cover.company)
    painter.setPen(QPen(style.accent, mm(0.3)))
    rule_y = mm(MARGIN_MM) - mm(1)
    painter.drawLine(QPointF(x0, rule_y), QPointF(x0 + width, rule_y))


def write_pdf(doc, image_paths, output_path):
    """Write ``doc`` to ``output_path``; returns {section anchor: page number}."""
    writer = QPdfWriter(output_path)
    writer.setResolution(DPI)
    writer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait,
                                     QMarginsF(0, 0, 0, 0)))
    writer.setTitle(doc.title)
    writer.setCreator("PartReview %s" % __version__)  # Producer is set by Qt itself
    if doc.author:
        writer.setAuthor(doc.author)
    page_w, page_h = writer.width(), writer.height()
    style = _Style(writer, doc.accent)
    layout = layout_document(doc, image_paths, style, page_w, page_h)

    painter = QPainter(writer)
    painter.setRenderHint(QPainter.Antialiasing)
    total = len(layout.pages)
    for number, ops in enumerate(layout.pages, start=1):
        if number > 1:
            writer.newPage()
        for op in ops:
            op(painter)
        if number > layout.cover_pages:
            header = not (number == 1 and layout.title_on_first_page)
            _paint_header_footer(painter, doc, style, number, total, page_w, page_h, header)
    painter.end()
    return dict(layout.anchor_pages)
