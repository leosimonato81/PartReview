# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Cover logo: box sizes and print sharpness (pure, no Qt).

A vector logo (SVG) is drawn at whatever resolution the page needs, so it is
always sharp. A raster logo (PNG/JPG) has a fixed number of pixels: printed in
the cover box it gets an effective resolution in dots per inch (dpi). Below
MIN_PRINT_DPI it may look blurry on paper; that is information for the user,
not an error (the report is still generated).
"""

from dataclasses import dataclass

MM_PER_INCH = 25.4
# 300 dpi is the usual print-shop standard; 150 dpi is the usual minimum for
# acceptable print quality of images viewed at reading distance.
MIN_PRINT_DPI = 150.0
GOOD_PRINT_DPI = 300.0

# Logo boxes (width, height) in mm. The logo keeps its proportions inside.
FULL_COVER_BOX_MM = (45.0, 22.0)  # dedicated cover page
COMPACT_COVER_BOX_MM = (28.0, 14.0)  # title block of the quick summary
_BOXES = (FULL_COVER_BOX_MM, COMPACT_COVER_BOX_MM)

VECTOR_EXTENSIONS = (".svg", ".svgz")


def is_vector(path: str) -> bool:
    return path.lower().endswith(VECTOR_EXTENSIONS)


def fitted_size_mm(px_w: int, px_h: int, box_mm: tuple[float, float]) -> tuple[float, float]:
    """Printed size of a px_w x px_h image fitted (proportions kept) in box_mm."""
    if px_w <= 0 or px_h <= 0:
        raise ValueError("image size must be positive")
    scale = min(box_mm[0] / px_w, box_mm[1] / px_h)
    return px_w * scale, px_h * scale


def print_dpi(px_w: int, px_h: int, box_mm: tuple[float, float]) -> float:
    """Effective resolution of the image printed in box_mm."""
    width_mm, _ = fitted_size_mm(px_w, px_h, box_mm)
    return px_w / (width_mm / MM_PER_INCH)


@dataclass(frozen=True)
class LogoSharpness:
    vector: bool
    dpi: float = 0.0  # lowest effective dpi among the cover boxes (raster only)
    min_width_px: int = 0  # width needed to reach GOOD_PRINT_DPI in every box

    @property
    def blurry(self) -> bool:
        return not self.vector and self.dpi < MIN_PRINT_DPI

    @property
    def level(self) -> str:
        """"vector", "good" (>= 300 dpi), "acceptable" (>= 150 dpi) or "blurry"."""
        if self.vector:
            return "vector"
        if self.dpi >= GOOD_PRINT_DPI:
            return "good"
        return "acceptable" if self.dpi >= MIN_PRINT_DPI else "blurry"


def check_sharpness(path: str, px_w: int = 0, px_h: int = 0) -> LogoSharpness:
    """Sharpness of a logo file of the given pixel size (ignored for vectors)."""
    if is_vector(path):
        return LogoSharpness(vector=True)
    dpi = min(print_dpi(px_w, px_h, box) for box in _BOXES)
    needed = max(fitted_size_mm(px_w, px_h, box)[0] / MM_PER_INCH * GOOD_PRINT_DPI
                 for box in _BOXES)
    return LogoSharpness(vector=False, dpi=dpi, min_width_px=int(round(needed)))


def raster_size_px(box_mm: tuple[float, float], aspect: float, dpi: float = GOOD_PRINT_DPI):
    """Pixel size to rasterize a vector logo of width/height ``aspect`` for box_mm."""
    if aspect <= 0:
        raise ValueError("aspect must be positive")
    width_mm = min(box_mm[0], box_mm[1] * aspect)
    width = max(1, int(round(width_mm / MM_PER_INCH * dpi)))
    return width, max(1, int(round(width / aspect)))
