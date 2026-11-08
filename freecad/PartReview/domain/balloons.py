# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Where to put a numbered balloon on a figure (pure, no Qt).

Like a callout on a technical drawing: the balloon sits on the empty background,
outside the part, as close as possible to its tip and preferably pointing away
from the part, so it never hides the color map; balloons never overlap.
``is_background(x, y)`` tells whether an image pixel is empty background.
"""

import math

_ANGLES = 24
_DISTANCES = (2.6, 3.4, 4.3, 5.4, 6.8, 8.5, 10.5, 13.0, 16.0, 20.0)  # in balloon radii
_OUTWARD_WEIGHT = 1.6  # radii added for pointing straight back towards the part
MIN_GAP = 2.3  # balloon centers at least 2.3 radii apart


CLEARANCE = 1.5  # radii of empty background around the center: half a radius of margin


def _disc_is_clear(x, y, radius, is_background):
    if not is_background(x, y):
        return False
    for ring in (0.8, CLEARANCE):
        for k in range(12):
            a = k * math.pi / 6
            if not is_background(x + ring * radius * math.cos(a), y + ring * radius * math.sin(a)):
                return False
    return True


def place_balloon(tip, radius, size, is_background, placed=(), away_from=None):
    """Balloon center for a leader ending at ``tip`` (pixels) in an image of ``size``."""
    u, v = tip
    width, height = size
    if away_from is None or (away_from[0] - u, away_from[1] - v) == (0, 0):
        outward = -math.pi / 4  # up-right when there is no better hint
    else:
        outward = math.atan2(v - away_from[1], u - away_from[0])
    candidates = []
    for d in _DISTANCES:
        for k in range(_ANGLES):
            a = 2 * math.pi * k / _ANGLES
            x, y = u + d * radius * math.cos(a), v + d * radius * math.sin(a)
            if not (radius + 2 <= x <= width - radius - 2 and radius + 2 <= y <= height - radius - 2):
                continue
            turn = 1.0 - math.cos(a - outward)  # 0 = straight outwards, 2 = back inwards
            candidates.append((d + _OUTWARD_WEIGHT * turn, x, y))
    candidates.sort()
    fallback = None
    for _, x, y in candidates:
        gap = min((math.hypot(x - px, y - py) for px, py in placed), default=math.inf)
        if gap < MIN_GAP * radius:
            continue
        if _disc_is_clear(x, y, radius, is_background):
            return x, y
        if fallback is None:
            fallback = (x, y)  # no empty background nearby: closest free spot
    if fallback is not None:
        return fallback
    return (min(max(u + 3 * radius, radius), width - radius),
            min(max(v - 3 * radius, radius), height - radius))
