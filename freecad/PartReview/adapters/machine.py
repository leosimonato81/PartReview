# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Leonardo Simonato
"""Memory and cores of this computer, without extra dependencies.

Linux (also inside Flatpak, which shows the host's /proc/meminfo): tested.
Windows (GlobalMemoryStatusEx) and macOS (sysctl + vm_stat): written from the
documented APIs, NOT tested yet.
"""

import ctypes
import os
import subprocess
import sys

import FreeCAD as App  # type: ignore

from ..domain.mesh_budget import MachineProfile

_MB = 1024.0 * 1024.0


def _linux():
    values = {}
    with open("/proc/meminfo") as fh:
        for line in fh:
            key, _, rest = line.partition(":")
            values[key] = float(rest.split()[0]) / 1024.0  # kB -> MB
    total = values["MemTotal"]
    if "MemAvailable" in values:
        return total, values["MemAvailable"], False
    free = values.get("MemFree", 0.0) + values.get("Cached", 0.0) + values.get("Buffers", 0.0)
    return total, free, True


def _windows():
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("GlobalMemoryStatusEx failed")
    return status.ullTotalPhys / _MB, status.ullAvailPhys / _MB, False


def _macos():
    total = float(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                                 text=True, timeout=5, check=True).stdout) / _MB
    out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5,
                         check=True).stdout
    page = 4096
    pages = {}
    for line in out.splitlines():
        if "page size of" in line:
            page = int(line.split("page size of")[1].split()[0])
        key, _, value = line.partition(":")
        if value.strip().rstrip(".").isdigit():
            pages[key.strip()] = int(value.strip().rstrip("."))
    free = sum(pages.get(k, 0) for k in ("Pages free", "Pages inactive", "Pages speculative"))
    return total, free * page / _MB, False


def machine_profile() -> MachineProfile:
    """Total and currently free memory (MB) and number of cores."""
    cores = os.cpu_count() or 1
    try:
        if sys.platform.startswith("linux"):
            total, available, estimated = _linux()
        elif sys.platform == "win32":
            total, available, estimated = _windows()
        elif sys.platform == "darwin":
            total, available, estimated = _macos()
        else:
            raise OSError("unsupported platform %s" % sys.platform)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, AttributeError) as err:
        # Expected on unusual systems: fall back to a cautious guess and say so.
        App.Console.PrintWarning("PartReview: free memory not readable (%s); "
                                 "assuming 2 GB free\n" % err)
        return MachineProfile(total_mb=4096.0, available_mb=2048.0, cores=cores, estimated=True)
    return MachineProfile(total_mb=total, available_mb=available, cores=cores,
                          estimated=estimated)
