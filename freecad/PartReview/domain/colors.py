# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Accent color that stays legible on white paper (pure, no Qt).

Rules from WCAG 2.x (W3C Web Content Accessibility Guidelines):
- relative luminance and contrast ratio, success criterion 1.4.3 definitions;
- text needs a contrast ratio of at least 4.5:1 (SC 1.4.3, normal text);
- graphical objects (bands, rules, bars) need at least 3:1 (SC 1.4.11).

When the user's color does not reach a ratio, a darker shade of the SAME hue
(mixed with black) is used only where it fails; dark colors are kept as chosen.
"""

from dataclasses import dataclass

RGB = tuple[float, float, float]  # 0..1

WHITE: RGB = (1.0, 1.0, 1.0)
TEXT_MIN_CONTRAST = 4.5
GRAPHIC_MIN_CONTRAST = 3.0
TABLE_HEADER_TINT = 0.88  # header background = shade mixed with 88 % white
_SEARCH_STEPS = 30  # bisection steps: 2**-30 is far below one 8-bit color step


def _linear(channel: float) -> float:
    """sRGB channel (0..1) to linear light, as in the WCAG definition."""
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: RGB) -> float:
    r, g, b = (_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: RGB, b: RGB) -> float:
    """WCAG contrast ratio, from 1 (same color) to 21 (black on white)."""
    la, lb = relative_luminance(a), relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def shade(rgb: RGB, amount: float) -> RGB:
    """Mix with black; amount 0 = the color, 1 = black."""
    return tuple(c * (1.0 - amount) for c in rgb)


def tint(rgb: RGB, amount: float) -> RGB:
    """Mix with white; amount 0 = the color, 1 = white."""
    return tuple(c + (1.0 - c) * amount for c in rgb)


def darken_to_contrast(rgb: RGB, minimum: float, background: RGB = WHITE) -> RGB:
    """The lightest shade of ``rgb`` with at least ``minimum`` contrast on ``background``."""
    if contrast_ratio(rgb, background) >= minimum:
        return tuple(rgb)
    def candidate(amount):  # rounded to 8-bit, as it will be written in the PDF/HTML
        return to_rgb(to_hex(shade(rgb, amount)))

    low, high = 0.0, 1.0  # fails at low, passes at high (black on white is 21:1)
    for _ in range(_SEARCH_STEPS):  # fixed number of steps (CLAUDE.md rule 6)
        middle = (low + high) / 2.0
        if contrast_ratio(candidate(middle), background) >= minimum:
            high = middle
        else:
            low = middle
    return candidate(high)


@dataclass(frozen=True)
class AccentPalette:
    base: RGB  # the color the user chose
    text: RGB  # titles and headings (>= 4.5:1 on white)
    graphic: RGB  # bands, rules, chart bars (>= 3:1 on white)
    light: RGB  # table header background (dark text stays legible on it)

    @property
    def adjusted(self) -> bool:
        """True when the titles use a darker shade than the chosen color."""
        return to_hex(self.text) != to_hex(self.base)


def accent_palette(base: RGB) -> AccentPalette:
    graphic = darken_to_contrast(base, GRAPHIC_MIN_CONTRAST)
    return AccentPalette(base=tuple(base), text=darken_to_contrast(base, TEXT_MIN_CONTRAST),
                         graphic=graphic, light=tint(graphic, TABLE_HEADER_TINT))


def to_hex(rgb: RGB) -> str:
    return "#%02x%02x%02x" % tuple(int(round(max(0.0, min(1.0, c)) * 255)) for c in rgb)


def to_rgb(color: str) -> RGB:
    """'#rrggbb' -> (r, g, b) in 0..1."""
    return tuple(int(color[i:i + 2], 16) / 255.0 for i in (1, 3, 5))


def readable_on(background: RGB) -> RGB:
    """Black or white, whichever has more contrast on ``background`` (button labels)."""
    black, white = (0.0, 0.0, 0.0), WHITE
    return black if contrast_ratio(black, background) >= contrast_ratio(white, background) \
        else white


# Supports and loads (report balloons and the supports/loads figure), 0..255.
# Outside the result color map (blue-cyan-green-yellow-red) on purpose.
SUPPORT_RGB = (106, 27, 154)  # purple
LOAD_RGB = (230, 81, 0)  # deep orange
PART_RGB = (200, 200, 200)  # neutral gray part under them
