# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Physical quantities and number formatting.

The domain never decides which unit a value has: adapters read the unit from
the FreeCAD document (or the solver convention) and build a ``Quantity``.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Quantity:
    """A value that always travels together with its unit (e.g. 0.61, "MPa")."""

    value: float
    unit: str

    def __post_init__(self):
        if not isinstance(self.unit, str):
            raise TypeError("unit must be a string, got %r" % (self.unit,))
        if not math.isfinite(self.value):
            raise ValueError("value must be finite, got %r" % (self.value,))


def format_number(value: float, significant: int = 3, decimal_sep: str = ".") -> str:
    """Format with a fixed number of significant digits.

    Uses plain notation between 1e-3 and 1e6 and scientific notation outside.
    ``decimal_sep`` is "," for pt_BR and "." for en.
    """
    if significant < 1:
        raise ValueError("significant must be >= 1")
    if value == 0:
        return "0"
    # Round to the significant digits first, so 9.996 -> 10.0 gets exponent 1.
    rounded = float("%.*e" % (significant - 1, value))
    magnitude = abs(rounded)
    if 1e-3 <= magnitude < 1e6:
        exponent = math.floor(math.log10(magnitude))
        decimals = max(0, significant - 1 - exponent)
        text = "%.*f" % (decimals, rounded)
    else:
        text = "%.*e" % (significant - 1, value)
    return text.replace(".", decimal_sep)


def format_number_like(value: float, reference: float, significant: int = 3,
                       decimal_sep: str = ".") -> str:
    """Format ``value`` with the same decimals ``reference`` would get.

    Used for scales (legend ticks): 0 and 0.614 become "0.000" and "0.614"
    instead of "5.88e-06" and "0.614".
    """
    magnitude = abs(reference)
    if magnitude == 0 or not 1e-3 <= magnitude < 1e6:
        return format_number(value, significant, decimal_sep) if value else "0"
    decimals = max(0, significant - 1 - math.floor(math.log10(magnitude)))
    text = "%.*f" % (decimals, value)
    if float(text) == 0:
        text = text.lstrip("-")
    return text.replace(".", decimal_sep)


_SUPERSCRIPTS = {"^2": "²", "^3": "³", "^-1": "⁻¹"}


def pretty_unit(unit: str) -> str:
    """'kg/m^3' -> 'kg/m³' for display."""
    for plain, pretty in _SUPERSCRIPTS.items():
        unit = unit.replace(plain, pretty)
    return unit


def format_quantity(q: Quantity, significant: int = 3, decimal_sep: str = ".") -> str:
    """'0.614 MPa' / '0,614 MPa'. Unit-less quantities print only the number."""
    number = format_number(q.value, significant, decimal_sep)
    return "%s %s" % (number, pretty_unit(q.unit)) if q.unit else number


def is_raw_unit(unit: str) -> bool:
    """True for FreeCAD's internal composite units such as 'kg/(mm*s^2)' or
    'mm*kg/s^2', returned by unit schemas that define no readable unit for a
    quantity (found for stress and force in 7 of FreeCAD 1.1's 10 schemas).
    Readable units ('MPa', 'kg/m^3', 'mm', 'psi', '"', 'N') are not raw."""
    return "*" in unit or "(" in unit
