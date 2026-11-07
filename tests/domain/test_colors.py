# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import pytest

from freecad.PartReview.domain.colors import (
    GRAPHIC_MIN_CONTRAST,
    TEXT_MIN_CONTRAST,
    WHITE,
    accent_palette,
    contrast_ratio,
    darken_to_contrast,
    readable_on,
    relative_luminance,
    to_hex,
    to_rgb,
)

BLACK = (0.0, 0.0, 0.0)
INK = to_rgb("#1e1e1e")  # body text color of the report


# Reference values published with WCAG 2.x and widely used checkers.
def test_wcag_reference_values():
    assert relative_luminance(WHITE) == pytest.approx(1.0)
    assert relative_luminance(BLACK) == pytest.approx(0.0)
    assert contrast_ratio(BLACK, WHITE) == pytest.approx(21.0)
    assert contrast_ratio(WHITE, WHITE) == pytest.approx(1.0)
    # #767676 is the lightest grey that passes 4.5:1 on white; #777777 fails.
    assert contrast_ratio(to_rgb("#767676"), WHITE) == pytest.approx(4.54, abs=0.01)
    assert contrast_ratio(to_rgb("#777777"), WHITE) < TEXT_MIN_CONTRAST
    # Pure red on white is 4.0:1; yellow on white is about 1.07:1.
    assert contrast_ratio(to_rgb("#ff0000"), WHITE) == pytest.approx(4.0, abs=0.01)
    assert contrast_ratio(to_rgb("#ffff00"), WHITE) == pytest.approx(1.07, abs=0.01)


def test_ratio_is_symmetric():
    a, b = to_rgb("#1f4a7d"), to_rgb("#ffcc00")
    assert contrast_ratio(a, b) == pytest.approx(contrast_ratio(b, a))


@pytest.mark.parametrize("color", ["#000000", "#1f4a7d", "#7a1f2b", "#767676"])
def test_dark_colors_are_kept_as_chosen(color):
    palette = accent_palette(to_rgb(color))
    assert to_hex(palette.text) == color and to_hex(palette.graphic) == color
    assert not palette.adjusted


@pytest.mark.parametrize("color", ["#ffff00", "#ffffff", "#ff0000", "#90ee90", "#87ceeb",
                                   "#ffcc00", "#00ffff"])
def test_light_colors_get_legible_shades_of_the_same_hue(color):
    base = to_rgb(color)
    palette = accent_palette(base)
    assert palette.adjusted
    assert contrast_ratio(palette.text, WHITE) >= TEXT_MIN_CONTRAST
    assert contrast_ratio(palette.graphic, WHITE) >= GRAPHIC_MIN_CONTRAST
    assert contrast_ratio(INK, palette.light) >= TEXT_MIN_CONTRAST  # table header text
    # same hue: channel proportions are kept (only mixed with black)
    biggest = max(range(3), key=lambda i: base[i])
    for i in range(3):
        if base[biggest] > 0:
            assert palette.text[i] / palette.text[biggest] == pytest.approx(
                base[i] / base[biggest], abs=0.02)


def test_shade_is_the_lightest_that_passes():
    shade = darken_to_contrast(to_rgb("#ffff00"), TEXT_MIN_CONTRAST)
    assert contrast_ratio(shade, WHITE) >= TEXT_MIN_CONTRAST
    lighter = tuple(min(1.0, c + 2 / 255) for c in shade)
    assert contrast_ratio(lighter, WHITE) < TEXT_MIN_CONTRAST


def test_graphic_can_stay_lighter_than_text():
    palette = accent_palette(to_rgb("#ff0000"))  # 4.0:1: fine for bands, not for text
    assert to_hex(palette.graphic) == "#ff0000"
    assert to_hex(palette.text) != "#ff0000"


def test_button_label_color():
    assert readable_on(to_rgb("#ffff00")) == BLACK
    assert readable_on(to_rgb("#1f4a7d")) == WHITE
    assert readable_on(BLACK) == WHITE


def test_hex_round_trip():
    assert to_hex(to_rgb("#1f4a7d")) == "#1f4a7d"
