# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import pytest

from freecad.PartReview.domain.blocks import DEFAULT_ACCENT, DEFAULT_ACCENT_HEX
from freecad.PartReview.domain.logo import (
    COMPACT_COVER_BOX_MM,
    FULL_COVER_BOX_MM,
    MIN_PRINT_DPI,
    check_sharpness,
    fitted_size_mm,
    is_vector,
    print_dpi,
    raster_size_px,
)
from freecad.PartReview.domain.templates import accent_rgb


def test_default_accent_is_black_in_both_forms():
    assert DEFAULT_ACCENT_HEX == "#000000"
    assert accent_rgb(DEFAULT_ACCENT_HEX) == pytest.approx(DEFAULT_ACCENT)


def test_vector_detection():
    assert is_vector("/a/Logo.SVG") and is_vector("x.svgz")
    assert not is_vector("x.png") and not is_vector("svg.jpg")


def test_fitted_size_keeps_proportions():
    w, h = fitted_size_mm(400, 100, FULL_COVER_BOX_MM)  # wide: limited by width
    assert (w, h) == pytest.approx((60.0, 15.0))
    w, h = fitted_size_mm(100, 400, FULL_COVER_BOX_MM)  # tall: limited by height
    assert (w, h) == pytest.approx((7.5, 30.0))


def test_print_dpi_matches_pdfimages_on_real_reports():
    # A 537 x 600 px PNG logo; pdfimages measured 693 ppi on the full cover
    # (45 x 22 mm box in v1.3.1) and 1089 ppi on the compact one.
    assert print_dpi(537, 600, (45.0, 22.0)) == pytest.approx(693, abs=1)
    assert print_dpi(537, 600, COMPACT_COVER_BOX_MM) == pytest.approx(1089, abs=1)


def test_small_raster_is_reported_blurry_with_needed_width():
    sharp = check_sharpness("logo.png", 120, 50)
    assert not sharp.vector and sharp.blurry
    assert sharp.dpi == pytest.approx(120 / (60 / 25.4))  # ~51 dpi, worst box
    assert sharp.min_width_px == 709  # 60 mm at 300 dpi


def test_large_raster_is_fine_and_vector_never_blurry():
    sharp = check_sharpness("logo.jpg", 300, 300)
    assert sharp.dpi > MIN_PRINT_DPI and not sharp.blurry
    assert check_sharpness("logo.svg") == check_sharpness("logo.svg", 1, 1)
    assert not check_sharpness("logo.svg").blurry


def test_svg_raster_size_follows_box_and_aspect():
    assert raster_size_px(FULL_COVER_BOX_MM, 676 / 697, 600) == (687, 708)
    assert raster_size_px(COMPACT_COVER_BOX_MM, 2.0, 300) == (331, 166)  # 165.5 rounds to 166


@pytest.mark.parametrize("bad", [(0, 10), (10, 0), (-1, 5)])
def test_invalid_sizes_raise(bad):
    with pytest.raises(ValueError):
        fitted_size_mm(*bad, FULL_COVER_BOX_MM)


@pytest.mark.parametrize("size, level", [((2000, 800), "good"), ((500, 200), "acceptable"),
                                         ((120, 50), "blurry")])
def test_sharpness_levels(size, level):
    assert check_sharpness("logo.png", *size).level == level
    assert check_sharpness("logo.svg").level == "vector"


def test_every_sharpness_level_has_a_message_in_both_languages():
    from freecad.PartReview.domain.i18n import Translator
    for language in ("pt_BR", "en"):
        tr = Translator(language)
        for level in ("vector", "good", "acceptable", "blurry"):
            assert tr.has("ui.logo_info." + level)
