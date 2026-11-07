# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Open the cover logo with Qt: check it, measure it and draw it sharp.

SVG files are drawn with QSvgRenderer at print resolution (QImage would use the
file's own, often small, size and look blurry). Raster files are read as they are.
"""

import os

import FreeCAD as App  # type: ignore
from PySide6.QtCore import Qt  # type: ignore
from PySide6.QtGui import QImage, QImageReader, QPainter  # type: ignore

from ..domain.logo import is_vector, raster_size_px

try:
    from PySide6.QtSvg import QSvgRenderer  # type: ignore
except ImportError:  # some builds ship without QtSvg: fall back to QImage
    QSvgRenderer = None

SVG_RENDER_DPI = 600.0  # twice the PDF resolution: sharp even when zoomed in

ERROR_MISSING = "config.error.logo"
ERROR_UNREADABLE = "config.error.logo_unreadable"


def _svg_renderer(path):
    if QSvgRenderer is None:
        return None
    renderer = QSvgRenderer(path)
    return renderer if renderer.isValid() else None


def _svg_aspect(renderer):
    box = renderer.viewBoxF()
    if box.width() > 0 and box.height() > 0:
        return box.width() / box.height()
    size = renderer.defaultSize()
    return size.width() / size.height() if size.width() > 0 and size.height() > 0 else 0.0


def inspect_logo(path):
    """Return (error_key, width_px, height_px); error_key is "" when the logo is usable."""
    if not os.path.isfile(path):
        return ERROR_MISSING, 0, 0
    if is_vector(path) and QSvgRenderer is not None:
        renderer = _svg_renderer(path)
        if renderer is None or _svg_aspect(renderer) <= 0:
            return ERROR_UNREADABLE, 0, 0
        size = renderer.defaultSize()
        return "", size.width(), size.height()
    reader = QImageReader(path)
    image = reader.read()
    if image.isNull():
        App.Console.PrintWarning("PartReview: logo %r not readable: %s\n"
                                 % (path, reader.errorString()))
        return ERROR_UNREADABLE, 0, 0
    return "", image.width(), image.height()


def load_logo(path, box_mm):
    """QImage of the logo for a cover box of ``box_mm`` (w, h); None when unusable."""
    if not path:
        return None
    renderer = _svg_renderer(path) if is_vector(path) else None
    if renderer is not None:
        aspect = _svg_aspect(renderer)
        if aspect > 0:
            width, height = raster_size_px(box_mm, aspect, SVG_RENDER_DPI)
            image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing)
            renderer.render(painter)
            painter.end()
            return image
    image = QImage(path)
    if image.isNull():
        # Checked before the report starts; reaching here means the file changed meanwhile.
        App.Console.PrintWarning("PartReview: logo %r could not be drawn; cover without logo\n"
                                 % path)
        return None
    return image
