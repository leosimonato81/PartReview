# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""The color scale shared by the 3D images and the PDF legend.

FreeCAD's ``setNodeColorByScalars`` maps a value s in [-1, 1] linearly through
blue (-1), cyan (-0.5), green (0), yellow (0.5), red (1) when the data spans
exactly [-1, 1] (verified in a headless render, 2026-11-06). We therefore send
FreeCAD ``to_unit_scalar(v)`` and draw the legend with ``STOPS``: both use the
same mapping, so the legend always matches the picture.
"""

# (position 0..1 along the legend, RGB 0..1)
STOPS = (
    (0.0, (0.0, 0.0, 1.0)),   # blue  = field minimum
    (0.25, (0.0, 1.0, 1.0)),  # cyan
    (0.5, (0.0, 1.0, 0.0)),   # green
    (0.75, (1.0, 1.0, 0.0)),  # yellow
    (1.0, (1.0, 0.0, 0.0)),   # red   = field maximum
)


def to_unit_scalar(value: float, vmin: float, vmax: float) -> float:
    """Map [vmin, vmax] linearly to [-1, 1] (clamped)."""
    if vmax <= vmin:
        return 0.0
    s = 2.0 * (value - vmin) / (vmax - vmin) - 1.0
    return max(-1.0, min(1.0, s))


def scalars_for_freecad(values, vmin: float, vmax: float) -> list[float]:
    """Values ready for setNodeColorByScalars.

    The extremes -1 and 1 are forced into the list so FreeCAD's own min/max
    (which it computes from the data) are exactly -1 and 1.
    """
    scalars = [to_unit_scalar(v, vmin, vmax) for v in values]
    if scalars:
        if min(scalars) > -1.0:
            scalars[scalars.index(min(scalars))] = -1.0
        if max(scalars) < 1.0:
            scalars[scalars.index(max(scalars))] = 1.0
    return scalars


def color_at(t: float) -> tuple[float, float, float]:
    """RGB at position t in [0, 1] of the legend (linear between stops)."""
    t = max(0.0, min(1.0, t))
    for (t0, c0), (t1, c1) in zip(STOPS, STOPS[1:]):
        if t <= t1:
            k = (t - t0) / (t1 - t0)
            return tuple(a + (b - a) * k for a, b in zip(c0, c1))
    return STOPS[-1][1]


def tick_values(vmin: float, vmax: float, count: int = 5) -> list[float]:
    """Evenly spaced legend labels from vmin to vmax (inclusive)."""
    if count < 2:
        raise ValueError("count must be >= 2")
    step = (vmax - vmin) / (count - 1)
    return [vmin + i * step for i in range(count)]
