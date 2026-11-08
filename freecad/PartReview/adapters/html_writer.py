# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Write the self-contained HTML version of a report (phase 6a, step h).

The page itself comes from domain.exporters.render_html; this adapter only
turns images into data: URIs (with the same numbered balloons as the PDF).
"""

import base64
import mimetypes

from PySide6.QtCore import QBuffer, QByteArray, QIODevice  # type: ignore
from PySide6.QtGui import QImage  # type: ignore

from ..domain.blocks import Figure
from ..domain.exporters import render_html
from .pdf_writer import draw_figure


def _png_uri(image):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return "data:image/png;base64," + base64.b64encode(bytes(data)).decode("ascii")


def _file_uri(path):
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as fh:
        return "data:%s;base64,%s" % (mime, base64.b64encode(fh.read()).decode("ascii"))


def write_html(doc, image_paths, output_path, language):
    figures = {b.view_index: b for b in doc.blocks if isinstance(b, Figure)}
    uris = [_png_uri(draw_figure(QImage(path), figures[i]) if i in figures else QImage(path))
            for i, path in enumerate(image_paths)]
    logo = _file_uri(doc.cover.logo_path) if doc.cover.logo_path else ""
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(render_html(doc, uris, logo, language))
    return output_path
