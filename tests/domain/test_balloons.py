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


def test_leaders_do_not_cross():
    from freecad.PartReview.domain.balloons import segments_cross, untangle
    assert segments_cross((0, 0), (10, 10), (0, 10), (10, 0))
    assert not segments_cross((0, 0), (10, 0), (0, 5), (10, 5))
    part = block(200, 150, 600, 450)
    placed, leaders = [], []
    tips = [(300, 300), (320, 310), (500, 200), (560, 420), (210, 440), (590, 160)]
    for tip in tips:
        c = place_balloon(tip, R, (W, H), part, placed, (400, 300), leaders)
        placed.append(c)
        leaders.append((tip, c))
    for i, (a, b) in enumerate(leaders):
        for c, d in leaders[i + 1:]:
            assert not segments_cross(a, b, c, d)
    crossed = untangle([[(0, 0), (10, 10)], [(0, 10), (10, 0)]])
    assert not segments_cross(crossed[0][0], crossed[0][1], crossed[1][0], crossed[1][1])
