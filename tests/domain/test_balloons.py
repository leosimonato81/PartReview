# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import math

from freecad.PartReview.domain.balloons import MIN_GAP, place_balloon

W, H, R = 800, 600, 14.0


def block(x0, y0, x1, y1):
    """Background everywhere except a rectangular 'part'."""
    return lambda x, y: not (x0 <= x <= x1 and y0 <= y <= y1)


def clear(x, y, is_bg):  # balloon plus half a radius of margin is all background
    return all(is_bg(x + 1.5 * R * math.cos(a), y + 1.5 * R * math.sin(a))
               for a in [k * math.pi / 6 for k in range(12)]) and is_bg(x, y)


def test_balloon_for_a_tip_inside_the_part_goes_to_the_background():
    part = block(200, 150, 600, 450)
    tip = (300, 300)  # well inside the part
    x, y = place_balloon(tip, R, (W, H), part, away_from=(400, 300))
    assert clear(x, y, part)
    assert x < 200  # left of the part: outwards from the centre, nearest edge


def test_balloons_never_overlap():
    part = block(200, 150, 600, 450)
    placed = []
    for tip in [(590, 160), (595, 165), (585, 170)]:  # three tips at the same corner
        placed.append(place_balloon(tip, R, (W, H), part, placed, away_from=(400, 300)))
    for i, a in enumerate(placed):
        for b in placed[i + 1:]:
            assert math.hypot(a[0] - b[0], a[1] - b[1]) >= MIN_GAP * R - 1e-9


def test_balloon_stays_inside_the_image():
    part = block(0, 0, 790, 590)  # almost everything is the part
    x, y = place_balloon((780, 580), R, (W, H), part, away_from=(400, 300))
    assert R <= x <= W - R and R <= y <= H - R
