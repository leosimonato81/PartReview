# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import math

import pytest

from freecad.PartReview.domain.units import Quantity, format_number, format_quantity


@pytest.mark.parametrize("value, expected", [
    (0.613703, "0.614"),
    (12000.0, "12000"),
    (5.88409e-06, "5.88e-06"),
    (1.0, "1.00"),
    (9.996, "10.0"),
    (-0.0012345, "-0.00123"),
    (0, "0"),
    (2.5e7, "2.50e+07"),
])
def test_format_number_significant_digits(value, expected):
    assert format_number(value) == expected


def test_format_number_uses_decimal_separator():
    assert format_number(0.613703, decimal_sep=",") == "0,614"
    assert format_number(5.88409e-06, decimal_sep=",") == "5,88e-06"


def test_format_number_rejects_bad_digits():
    with pytest.raises(ValueError):
        format_number(1.0, significant=0)


def test_format_quantity_keeps_unit_untouched():
    assert format_quantity(Quantity(0.613703, "MPa"), decimal_sep=",") == "0,614 MPa"
    assert format_quantity(Quantity(0.3, "")) == "0.300"


def test_quantity_requires_string_unit_and_finite_value():
    with pytest.raises(TypeError):
        Quantity(1.0, None)
    with pytest.raises(ValueError):
        Quantity(math.nan, "mm")


def test_quantity_is_immutable():
    q = Quantity(1.0, "mm")
    with pytest.raises(AttributeError):
        q.value = 2.0


def test_format_number_like_uses_reference_decimals():
    from freecad.PartReview.domain.units import format_number_like
    assert format_number_like(5.88e-06, 0.614) == "0.000"
    assert format_number_like(0.30675, 0.614, decimal_sep=",") == "0,307"
    assert format_number_like(4.68e-05, 1.87e-04) == "4.68e-05"
    assert format_number_like(0.0, 1.87e-04) == "0"
    assert format_number_like(1500.0, 3000.0) == "1500"


def test_pretty_unit():
    from freecad.PartReview.domain.units import pretty_unit
    assert pretty_unit("kg/m^3") == "kg/m³"
    assert format_quantity(Quantity(7900.0, "kg/m^3")) == "7900 kg/m³"


@pytest.mark.parametrize("unit, raw", [
    ("kg/(mm*s^2)", True), ("mm*kg/s^2", True),          # seen in FreeCAD 1.1 schemas
    ("MPa", False), ("kPa", False), ("psi", False), ("ksi", False), ("N", False),
    ("MN", False), ("kg/m^3", False), ("mm", False), ('"', False), ("in", False),
    ("ft", False), ("m", False), ("GPa", False),
])
def test_is_raw_unit(unit, raw):
    from freecad.PartReview.domain.units import is_raw_unit
    assert is_raw_unit(unit) is raw
