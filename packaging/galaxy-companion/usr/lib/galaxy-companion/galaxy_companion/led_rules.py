# SPDX-License-Identifier: MIT
"""Rules for a multicolour status LED: what lights it, in which colour and how.

A rule is a plain dict, stored as a JSON list in the `led-rules` setting:

    {"id": "a1b2", "enabled": true, "condition": "notification",
     "app": "org.telegram.desktop", "app_name": "Telegram",
     "battery_min": 0, "battery_max": 15, "power": "unplugged",
     "color": "#3584e4", "effect": "breathe"}

The rules are read top to bottom and the first one that holds decides the
LED, so order is priority.  Plain Python: the window edits rules, the session
backend evaluates them.
"""
import json
import re
import uuid

from .i18n import N_, _

CONDITIONS = (
    ("notification", N_("A notification arrives")),
    ("battery", N_("The battery level is in a range")),
    ("charging", N_("Charging")),
    ("charged", N_("Fully charged")),
    ("media", N_("Music or video is playing")),
    ("signal", N_("A custom signal is on")),
    ("command", N_("A command succeeds")),
)
# Whether the charger matters to a battery rule.
POWER = (
    ("any", N_("Either way")),
    ("unplugged", N_("Unplugged")),
    ("plugged", N_("Plugged in")),
)
# Offered only with "Custom conditions" on, and ignored while it is off.
ADVANCED = frozenset({"signal", "command"})
SIGNAL = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
COMMAND_INTERVAL = (30, 3600)   # seconds between runs: lower and upper bound
COMMAND_TIMEOUT = 10            # seconds a run may take before it counts as failed
EFFECTS = (
    ("solid", N_("Steady")),
    ("breathe", N_("Breathing")),
    ("blink-slow", N_("Slow blink")),
    ("blink-fast", N_("Fast blink")),
)
# (on ms, off ms) for the blink effects; breathing ramps over BREATHE_MS.
BLINK = {"blink-slow": (300, 2700), "blink-fast": (250, 250)}
BREATHE_MS = 1200

PALETTE = (
    ("#e01b24", N_("Red")),
    ("#ff7800", N_("Orange")),
    ("#f6d32d", N_("Yellow")),
    ("#33d17a", N_("Green")),
    ("#33c7de", N_("Cyan")),
    ("#3584e4", N_("Blue")),
    ("#9141ac", N_("Purple")),
    ("#e66198", N_("Pink")),
    ("#ffffff", N_("White")),
)
COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")


def new_rule(condition="notification", **values):
    rule = {"id": uuid.uuid4().hex[:8], "enabled": True, "condition": condition,
            "app": "", "app_name": "", "battery_min": 0, "battery_max": 15, "power": "any", "color": "#3584e4", "effect": "breathe",
            "signal": "", "command": "", "interval": 60}
    rule.update(values)
    return rule


def defaults():
    """What the LED did before anyone touched it, plus notifications."""
    return [
        new_rule("notification", color="#3584e4", effect="breathe"),
        new_rule("battery", battery_min=0, battery_max=15, power="unplugged", color="#e01b24", effect="blink-slow"),
        new_rule("charging", color="#ff7800", effect="solid"),
        new_rule("charged", color="#33d17a", effect="solid"),
    ]


def clean(rule):
    """A rule with every field valid, or None to drop it."""
    if isinstance(rule, dict) and rule.get("condition") == "battery-low":
        # Before 2.4: "below a threshold, not charging".
        rule = dict(rule, condition="battery", battery_min=0, battery_max=rule.get("threshold", 15),
                    power="unplugged")
    if not isinstance(rule, dict) or rule.get("condition") not in dict(CONDITIONS):
        return None
    out = new_rule(rule["condition"])
    out["id"] = str(rule.get("id") or out["id"])[:32]
    out["enabled"] = bool(rule.get("enabled", True))
    out["app"] = str(rule.get("app") or "")[:200]
    out["app_name"] = str(rule.get("app_name") or "")[:200]
    try:
        low, high = (min(100, max(0, int(rule.get(key, out[key])))) for key in ("battery_min", "battery_max"))
        out["battery_min"], out["battery_max"] = min(low, high), max(low, high)
    except (TypeError, ValueError):
        pass
    if rule.get("power") in dict(POWER):
        out["power"] = rule["power"]
    if SIGNAL.match(str(rule.get("signal") or "")):
        out["signal"] = rule["signal"]
    out["command"] = str(rule.get("command") or "")[:500]
    try:
        out["interval"] = min(COMMAND_INTERVAL[1], max(COMMAND_INTERVAL[0], int(rule.get("interval", 60))))
    except (TypeError, ValueError):
        pass
    if COLOR.match(str(rule.get("color", ""))):
        out["color"] = rule["color"].lower()
    if rule.get("effect") in dict(EFFECTS):
        out["effect"] = rule["effect"]
    return out


def load(text):
    """Rules from the setting; an empty setting means the defaults."""
    if not text:
        return defaults()
    try:
        value = json.loads(text)
    except ValueError:
        return defaults()
    return [rule for rule in map(clean, value if isinstance(value, list) else []) if rule]


def dump(rules):
    return json.dumps([clean(rule) for rule in rules if clean(rule)])


def rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def color_name(color):
    return next((_(name) for value, name in PALETTE if value == color.lower()), _("Custom colour"))


def title(rule):
    condition = rule["condition"]
    if condition == "notification":
        if rule.get("app_name"):
            return _("Notification from {app}").format(app=rule["app_name"])
        return _("Any notification")
    if condition == "battery":
        return _("Battery between {low} and {high} %").format(low=rule["battery_min"], high=rule["battery_max"])
    if condition == "signal":
        return _("Signal “{name}”").format(name=rule["signal"] or "…")
    if condition == "command":
        command = rule["command"] or "…"
        return _("Command: {command}").format(command=command if len(command) <= 40 else command[:39] + "…")
    return _(dict(CONDITIONS)[condition])


def subtitle(rule):
    parts = [_(dict(EFFECTS)[rule["effect"]]), color_name(rule["color"])]
    if rule["condition"] == "battery" and rule["power"] != "any":
        parts.append(_(dict(POWER)[rule["power"]]))
    return " · ".join(parts)


def _variants(name):
    """A desktop id with and without ".desktop": "org.telegram.desktop" is
    both an app id and, minus the suffix, what some apps send instead."""
    name = (name or "").lower()
    return {name, name.removesuffix(".desktop")} - {""}


def _app_matches(rule, sources):
    wanted = _variants(rule.get("app")) | ({rule["app_name"].lower()} if rule.get("app_name") else set())
    return any(_variants(source) & wanted for source in sources)


def matches(rule, status):
    """Whether `rule` holds for `status`, as the backend sees the device:

    status = {"battery": int|None, "battery_status": "Charging"|"Full"|...,
              "plugged": bool, "notifications": [set of app ids/names, ...],
              "media": bool}
    """
    if not rule.get("enabled"):
        return False
    condition = rule["condition"]
    level, state = status.get("battery"), status.get("battery_status", "")
    if condition == "notification":
        pending = status.get("notifications", ())
        if not rule.get("app"):
            return bool(pending)
        return any(_app_matches(rule, sources) for sources in pending)
    if condition == "battery":
        if level is None or not rule["battery_min"] <= level <= rule["battery_max"]:
            return False
        plugged = bool(status.get("plugged")) or state in ("Charging", "Full")
        return {"any": True, "unplugged": not plugged, "plugged": plugged}[rule["power"]]
    if condition == "charging":
        return state == "Charging"
    if condition == "charged":
        return state == "Full" or (status.get("plugged") and level is not None and level >= 100)
    if condition == "media":
        return bool(status.get("media"))
    if condition == "signal":
        return bool(rule["signal"]) and rule["signal"] in status.get("signals", ())
    if condition == "command":
        return bool(rule["command"]) and status.get("commands", {}).get(rule["command"]) is True
    return False


def usable(rules, advanced):
    """The rules the engine may consider: advanced ones only when allowed."""
    return [rule for rule in rules if advanced or rule["condition"] not in ADVANCED]


def choose(rules, status):
    return next((rule for rule in rules if matches(rule, status)), None)


def in_quiet_hours(hour, start, end):
    """Whether `hour` (0-23) falls in [start, end), which may cross midnight."""
    if start == end:
        return False
    return start <= hour < end if start < end else hour >= start or hour < end
