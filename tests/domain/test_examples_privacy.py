# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""The published example models must not carry personal paths or names."""

import glob
import os
import re
import zipfile

import pytest

EXAMPLES = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "..", "examples",
                                         "*.FCStd")))
PERSONAL = [rb"(?i)/home/", rb"(?i)/Users/", rb"(?i)C:\\Users", rb"(?i)leonardo",
            rb"(?i)/tmp/", rb"(?i)/var/tmp"]


def test_examples_exist():
    assert len(EXAMPLES) >= 4


@pytest.mark.parametrize("path", EXAMPLES, ids=os.path.basename)
def test_example_has_no_personal_data(path):
    archive = zipfile.ZipFile(path)
    hits = [(name, pattern) for name in archive.namelist()
            for pattern in PERSONAL if re.search(pattern, archive.read(name))]
    assert hits == []
