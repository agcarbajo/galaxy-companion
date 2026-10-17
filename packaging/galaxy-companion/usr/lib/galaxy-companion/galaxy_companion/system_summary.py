# SPDX-License-Identifier: MIT
"""Read a small public system summary without subprocesses or user data."""
import math
import os
from pathlib import Path
from html import escape
from . import device
from . import update_bundle
from .i18n import _


def read(path):
    try:
        return Path(path).read_text().strip().replace("\0", "")
    except (OSError, UnicodeError):
        return ""


MEMINFO = "/proc/meminfo"
# Sizes phones and tablets are sold with, in GB.  The kernel reports less
# than is fitted (firmware carve-outs), so the label is the next size up.
MARKETED_GB = (1, 1.5, 2, 3, 4, 6, 8, 12, 16, 18, 24, 32, 48, 64)


def os_release():
    release = {}
    for line in read("/etc/os-release").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            release[key] = value.strip('"\'')
    return release


def processor():
    cpu = next((line.split(":", 1)[1].strip() for line in read("/proc/cpuinfo").splitlines()
                if line.startswith(("model name", "Hardware")) and ":" in line), "")
    # /proc/cpuinfo on arm64 names no product; the profile knows the SoC.
    return device.current().soc or cpu or read("/sys/devices/soc0/machine")


def memory_kib():
    try:
        return int(next(line.split()[1] for line in read(MEMINFO).splitlines() if line.startswith("MemTotal:")))
    except (StopIteration, ValueError, IndexError):
        return 0


def marketed_memory(kib):
    """"16 GB" for the 15.2 GiB a 16 GB device reports; "" when unknown."""
    if kib <= 0:
        return ""
    gib = kib / 1024**2
    size = next((size for size in MARKETED_GB if size >= gib), math.ceil(gib))
    return f"{size:g} GB"


def rows():
    unknown = _("Unknown")
    installed = update_bundle.current()
    release = os_release()
    cpu = processor() or unknown
    memory, uptime = unknown, unknown
    total = memory_kib()
    if total:
        memory = _("{size} GiB usable").format(size=f"{total / 1024**2:.1f}")
    try:
        seconds = float(read("/proc/uptime").split()[0])
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Invalid uptime")
        days, minutes = divmod(int(seconds) // 60, 1440)
        hours, minutes = divmod(minutes, 60)
        uptime = _("{days} d · {hours} h · {minutes} min").format(days=days, hours=hours, minutes=minutes)
    except (IndexError, ValueError):
        pass
    return [(_("Port version"), str(installed.get("tag") or installed.get("version") or unknown)),
            (_("Kernel"), os.uname().release),
            ("Ubuntu", release.get("PRETTY_NAME") or unknown),
            (_("Processor"), cpu), (_("RAM"), memory), (_("Uptime"), uptime)]


def markup(values):
    return "<b>" + escape(_("System build")) + "</b>\n" + "\n".join(
        f"<b>{escape(title)}:</b> {escape(value)}" for title, value in values)


def text(values):
    return "\n".join(f"{title}: {value}" for title, value in values)
