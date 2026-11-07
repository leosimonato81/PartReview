# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato

import importlib
import pkgutil
import sys

import freecad.PartReview.domain as domain

FORBIDDEN = {"FreeCAD", "FreeCADGui", "PySide6", "PySide2", "pivy", "Part", "Fem"}


def test_every_domain_module_imports_without_freecad():
    names = [m.name for m in pkgutil.iter_modules(domain.__path__, domain.__name__ + ".")]
    assert names, "no domain modules found"
    for name in names:
        importlib.import_module(name)
    assert not FORBIDDEN & set(sys.modules)
