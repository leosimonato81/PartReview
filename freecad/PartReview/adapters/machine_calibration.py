# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""What THIS computer has shown in earlier CalculiX trials (solve speed).

Each computer learns its own speed from the trials made on it; nothing is assumed
from another machine. The file is discarded when the computer changes (memory,
cores, system, FreeCAD version or CalculiX executable).
"""

import json
import os
import sys
import time

import FreeCAD as App  # type: ignore

from ..domain.solver_model import SolverSample
from .mesh_runner import ccx_binary

KEEP = 12  # most recent trials kept


def _file():
    return os.path.join(App.getUserAppDataDir(), "PartReview", "machine_calibration.json")


def signature(machine):
    return {"total_gb": round(machine.total_mb / 512.0) / 2.0, "cores": machine.cores,
            "platform": sys.platform, "freecad": ".".join(App.Version()[:3]),
            "ccx": ccx_binary() or ""}


def load(machine):
    """(samples, date text) measured earlier on this same computer, or ([], "")."""
    try:
        with open(_file(), encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("signature") != signature(machine):
            return [], ""
        samples = [SolverSample(int(n), float(s), float(m)) for n, s, m in data["samples"]]
        return [s for s in samples if s.measured], data.get("date", "")
    except FileNotFoundError:
        return [], ""
    except (OSError, ValueError, KeyError, TypeError) as err:
        App.Console.PrintWarning("PartReview: machine calibration ignored: %s\n" % err)
        return [], ""


def save(machine, new_samples):
    old, _ = load(machine)
    samples = (old + [s for s in new_samples if s.measured])[-KEEP:]  # unmeasured: no data
    data = {"signature": signature(machine), "date": time.strftime("%Y-%m-%d"),
            "samples": [[s.nodes, round(s.seconds, 3), round(s.peak_mb, 1)] for s in samples]}
    path = _file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, path)
    except OSError as err:
        App.Console.PrintWarning("PartReview: machine calibration not saved: %s\n" % err)
