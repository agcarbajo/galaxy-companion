# SPDX-License-Identifier: MIT
"""Stop charging at a chosen battery level, where the device is known to allow it.

Two ways, chosen by the profile's `charge_limit.method`:

- `threshold`: the kernel keeps the limit itself
  (`charge_control_end_threshold`, and the start threshold when there is one).
- `charge-behaviour`: the charger can only be told to stop or resume
  (`charge_behaviour`: `inhibit-charge` / `auto`), so the system service polls
  the battery and does it, resuming a few points below the limit.

Only devices whose profile lists `charge-limit` get the option: a charger
that silently ignores the request would be worse than no option at all.
The choice lives in STATE, readable by everyone and written only by the
privileged helper.
"""
import json
import os
from pathlib import Path

from . import device

STATE = Path("/var/lib/galaxy-companion/charge-limit.json")
POWER_SUPPLY = Path("/sys/class/power_supply")
LEVELS = (60, 65, 70, 75, 80, 85, 90, 95)
DEFAULT_LIMIT = 80
# Points below the limit where charging resumes: avoids toggling the charger
# for every percent the gauge wobbles.
RESUME_BELOW = 5


def config():
    return device.current().charge_limit if device.current().has("charge-limit") else {}


def available():
    settings = config()
    return settings.get("method") in ("threshold", "charge-behaviour")


def levels():
    return tuple(config().get("levels") or LEVELS)


def load(path=STATE):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        value = {}
    limit = value.get("limit")
    return {
        "enabled": bool(value.get("enabled", False)),
        "limit": limit if limit in levels() else DEFAULT_LIMIT,
    }


def save(enabled, limit, path=STATE):
    if limit not in levels():
        raise ValueError(f"{limit} is not an allowed level")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"enabled": bool(enabled), "limit": int(limit)}))
    os.chmod(temp, 0o644)
    os.replace(temp, path)


def _read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


def battery_level(root=POWER_SUPPLY):
    name = config().get("battery", "")
    try:
        return int(_read(Path(root) / name / "capacity"))
    except ValueError:
        return None


def _write(path, value):
    Path(path).write_text(f"{value}\n")


def apply(state, root=POWER_SUPPLY, current=None):
    """Bring the charger in line with `state`; returns what was written, if anything."""
    settings = config()
    method = settings.get("method")
    root = Path(root)
    if method == "threshold":
        battery = root / settings.get("battery", "")
        end = state["limit"] if state["enabled"] else 100
        _write(battery / "charge_control_end_threshold", end)
        start = battery / "charge_control_start_threshold"
        if start.exists():
            _write(start, max(0, end - RESUME_BELOW) if state["enabled"] else 0)
        return f"threshold {end}"
    if method == "charge-behaviour":
        attribute = root / settings.get("charger", "") / "charge_behaviour"
        level = battery_level(root) if current is None else current
        if not state["enabled"] or level is None:
            wanted = "auto"
        elif level >= state["limit"]:
            wanted = "inhibit-charge"
        elif level <= state["limit"] - RESUME_BELOW:
            wanted = "auto"
        else:
            return None  # inside the window: leave the charger as it is
        # The file reads like "auto [inhibit-charge]", the active one bracketed.
        if f"[{wanted}]" not in _read(attribute):
            _write(attribute, wanted)
            return wanted
        return None
    return None


def release(root=POWER_SUPPLY):
    """Never leave charging stopped behind: used when the service stops."""
    settings = config()
    if settings.get("method") == "charge-behaviour":
        attribute = Path(root) / settings.get("charger", "") / "charge_behaviour"
        if "[inhibit-charge]" in _read(attribute):
            _write(attribute, "auto")
