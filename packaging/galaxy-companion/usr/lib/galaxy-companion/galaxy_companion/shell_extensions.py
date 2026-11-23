# SPDX-License-Identifier: MIT
"""Keep GNOME Shell extensions usable after a Shell crash, on any device.

When Shell dies in the first minute of a session GNOME assumes an extension
did it and sets disable-user-extensions, which nothing ever clears: a single
crash from any cause leaves every extension off across logins and reboots.

Here that crash is recorded, and the next session turns extensions back on.
Three crashes in a row without a session that survived are a crash loop, and
then GNOME's protection stands until the person restarts extensions by hand.
A switch the person turned off themselves is never touched: only a crash
leaves a record.
"""
import json
import os
from pathlib import Path
import tempfile
import time

from gi.repository import Gio, GLib

SCHEMA = "org.gnome.shell"
OFF_KEY = "disable-user-extensions"
DISABLED_KEY = "disabled-extensions"
BUS_NAME = "org.gnome.Shell.Extensions"
OBJECT_PATH = "/org/gnome/Shell/Extensions"
# misc/extensionUtils.js, ExtensionState
ACTIVE, INACTIVE, ERROR, OUT_OF_DATE = 1, 2, 3, 4
INITIALIZED, DEACTIVATING, ACTIVATING = 6, 7, 8
MAX_ATTEMPTS = 3
# GNOME only blames extensions for a crash in the first 60 seconds.
HEALTHY_SECONDS = 120
SETTLE_SECONDS = 15
# The unit's ConditionPathExists names this same file.
STATE = Path.home() / ".local/state/galaxy-companion/shell-extensions.json"


def settings():
    """org.gnome.shell, or None on a desktop that does not have it."""
    source = Gio.SettingsSchemaSource.get_default()
    schema = source.lookup(SCHEMA, True) if source else None
    if schema is None or not schema.has_key(OFF_KEY):
        return None
    return Gio.Settings.new(SCHEMA)


def available():
    desktops = os.environ.get("XDG_CURRENT_DESKTOP", "").upper().split(":")
    return "GNOME" in desktops and settings() is not None


def extensions():
    """What Shell reports: {uuid: {"state": …, "enabled": …}}."""
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    reply = bus.call_sync(BUS_NAME, OBJECT_PATH, BUS_NAME, "ListExtensions", None,
                          GLib.VariantType("(a{sa{sv}})"), Gio.DBusCallFlags.NONE, 8000, None)
    return reply.unpack()[0]


def _load():
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    saved = data.get("restart_disabled")
    if saved is not None and not (isinstance(saved, list) and all(isinstance(u, str) for u in saved)):
        del data["restart_disabled"]
    if not isinstance(data.get("attempts", 0), int):
        data["attempts"] = MAX_ATTEMPTS
    return data


def _write(data):
    """Save the state; with nothing to remember there is no file at all."""
    if not data:
        STATE.unlink(missing_ok=True)
        return
    STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=STATE.name, dir=STATE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, STATE)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def record_crash(store):
    """Runs just before GNOME sets the switch: only a crash can reach this."""
    if store.get_boolean(OFF_KEY):
        return False    # Already off, by the person or by an earlier crash.
    data = _load()
    data["attempts"] = data.get("attempts", 0) + 1
    data["pending"] = True
    data.pop("held", None)
    _write(data)
    return True


def _notify_held():
    from .i18n import _
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                  "org.freedesktop.Notifications", "Notify",
                  GLib.Variant("(susssasa{sv}i)", (
                      "Galaxy Companion", 0, "io.github.agcarbajo.GalaxyCompanion",
                      _("Desktop extensions are off"),
                      _("GNOME Shell failed several times in a row. To turn them back on, open Galaxy Companion, then About and Troubleshooting."),
                      [], {}, -1)),
                  None, Gio.DBusCallFlags.NONE, 5000, None)


def recover(store, pause=time.sleep, notify=_notify_held):
    """At the start of a session: undo what a crash left behind."""
    data = _load()
    if not data:
        return "idle"
    if "restart_disabled" in data:      # A restart that never finished.
        store.set_strv(DISABLED_KEY, data.pop("restart_disabled"))
        Gio.Settings.sync()
        _write(data)
    if store.get_boolean(OFF_KEY):
        if data.get("held") or (data.get("pending") and data.get("attempts", 0) >= MAX_ATTEMPTS):
            data.update(held=True, pending=False)
            _write(data)
            try:
                notify()
            except GLib.Error:
                pass    # The state stays visible through the button.
            return "held"
        if not data.get("pending"):
            _write({})
            return "left-off"
        store.set_boolean(OFF_KEY, False)
        Gio.Settings.sync()
        data["pending"] = False
        _write(data)
    if data.get("attempts"):
        # Killed with the session if this one crashes too: the count stands.
        pause(HEALTHY_SECONDS)
    current = _load()
    if not current.get("pending") and "restart_disabled" not in current:
        _write({})
    return "restored"


def _wait(listing, pause, done):
    for _attempt in range(SETTLE_SECONDS * 4):
        report = listing()
        if done(report):
            return report
        pause(0.25)
    return listing()


def _enabled_settled(report):
    return all(info.get("state") not in (INACTIVE, INITIALIZED, ACTIVATING, DEACTIVATING)
               for info in report.values() if info.get("enabled"))


def restart(store, listing=extensions, pause=time.sleep):
    """Turn every extension back on and reload it, whatever its origin.

    disabled-extensions is the one key that also stops the session mode's own
    extensions (Ubuntu's dock, for one).  Its value is saved first, so a Shell
    crash halfway through cannot leave them all disabled.
    """
    data = _load()
    original = list(data.get("restart_disabled", store.get_strv(DISABLED_KEY)))
    data["restart_disabled"] = original
    _write(data)
    finished = False
    try:
        store.set_boolean(OFF_KEY, False)
        store.set_strv(DISABLED_KEY, original)
        Gio.Settings.sync()
        # Enabled but not running means it does not apply to this session mode.
        targets = sorted(uuid for uuid, info in _wait(listing, pause, _enabled_settled).items()
                         if info.get("enabled") and info.get("state") in (ACTIVE, ERROR))
        store.set_strv(DISABLED_KEY, original + [uuid for uuid in targets if uuid not in original])
        Gio.Settings.sync()
        _wait(listing, pause, lambda report: all(
            report.get(uuid, {}).get("state") not in (ACTIVE, ACTIVATING, DEACTIVATING)
            for uuid in targets))
        store.set_strv(DISABLED_KEY, original)
        Gio.Settings.sync()
        report = _wait(listing, pause, _enabled_settled)
        finished = True
    finally:
        if finished:
            _write({})  # Asked for by hand: the crash count starts over.
        else:
            store.set_strv(DISABLED_KEY, original)
            Gio.Settings.sync()
            data = _load()
            data.pop("restart_disabled", None)
            _write(data)
    return {
        "restarted": [uuid for uuid in targets if report.get(uuid, {}).get("state") == ACTIVE],
        "failed": [uuid for uuid in targets
                   if report.get(uuid, {}).get("state") not in (ACTIVE, OUT_OF_DATE)],
    }
