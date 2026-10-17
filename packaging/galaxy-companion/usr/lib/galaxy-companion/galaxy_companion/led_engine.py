# SPDX-License-Identifier: MIT
"""Runs the status LED rules inside the session backend.

It gathers what the rules can ask about (battery, charger, notifications
waiting to be seen, media playing), picks the first rule that holds and asks
`galaxy-companion-led` to show it, only when the result changes.

A notification counts as waiting until the person uses the device after it
arrived: Mutter's idle monitor says how long ago that was.  Without it, the
screen shield going away does the same job.
"""
import time
from pathlib import Path

from gi.repository import Gio, GLib

from . import led_rules

HELPER = "/usr/libexec/galaxy-companion-led"
POWER_SUPPLY = Path("/sys/class/power_supply")
TICK_SECONDS = 5
PREVIEW_SECONDS = 5
HELPER_TIMEOUT = 15  # seconds before a helper that never answers counts as failed


def _read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


def power_status(root=None):
    battery, state, plugged = None, "", False
    for supply in sorted(Path(root or POWER_SUPPLY).glob("*")):
        kind = _read(supply / "type")
        if kind == "Battery" and battery is None and _read(supply / "present") != "0":
            try:
                battery = int(_read(supply / "capacity"))
            except ValueError:
                continue
            state = _read(supply / "status")
        elif kind in ("Mains", "USB", "USB_C", "USB_PD") and _read(supply / "online") == "1":
            plugged = True
    return {"battery": battery, "battery_status": state, "plugged": plugged}


def notification_sources(interface, args):
    """Lower-case names a notification can be matched by: desktop id, app name."""
    sources = set()
    try:
        if interface == "org.freedesktop.Notifications":
            sources.add(str(args[0]))
            hints = args[6] if len(args) > 6 else {}
            if "desktop-entry" in hints:
                sources.add(str(hints["desktop-entry"]))
        else:  # org.gtk.Notifications.AddNotification(app_id, id, notification)
            sources.add(str(args[0]))
    except (IndexError, TypeError, KeyError):
        pass
    return {source.lower() for source in sources if source}


class LedEngine:
    def __init__(self, settings, run=None):
        self.settings = settings
        self.run = run or self._spawn
        self.pending = []          # [(monotonic time, sources)]
        self.shown = None
        self.queued = None
        self.busy = False
        self.preview = None
        self.preview_timer = None
        self.signals = set()       # turned on with `galaxy-companion --led-signal`
        self.command_results = {}  # command -> bool, from its last run
        self.command_due = {}      # command -> monotonic time of the next run
        self.command_running = set()
        self.bus = None
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.bus.signal_subscribe(None, "org.gnome.ScreenSaver", "ActiveChanged",
                                      "/org/gnome/ScreenSaver", None, Gio.DBusSignalFlags.NONE,
                                      self._screensaver_changed)
        except GLib.Error:
            self.bus = None
        for key in ("led-enabled", "led-rules", "led-brightness", "led-advanced", "led-quiet-enabled",
                    "led-quiet-start", "led-quiet-end"):
            settings.connect(f"changed::{key}", lambda *_: self.evaluate())
        self.timer = GLib.timeout_add_seconds(TICK_SECONDS, self._tick)
        self.evaluate()

    # -- inputs ---------------------------------------------------------------

    def notification(self, sources):
        if sources:
            self.pending.append((time.monotonic(), sources))
            self.evaluate()

    def set_signal(self, name, on):
        if not led_rules.SIGNAL.match(name or ""):
            return False
        (self.signals.add if on else self.signals.discard)(name)
        self.evaluate()
        return True

    # -- custom commands ------------------------------------------------------

    def _run_commands(self, rules):
        """Start the command rules that are due; results arrive later."""
        now = time.monotonic()
        wanted = {rule["command"]: rule["interval"] for rule in rules
                  if rule["condition"] == "command" and rule["enabled"] and rule["command"]}
        for command in list(self.command_results):
            if command not in wanted:  # rule deleted or changed: forget it
                self.command_results.pop(command, None)
                self.command_due.pop(command, None)
        for command, interval in wanted.items():
            if command in self.command_running or now < self.command_due.get(command, 0):
                continue
            self.command_due[command] = now + interval
            self._spawn_command(command)

    def _spawn_command(self, command):
        try:
            process = Gio.Subprocess.new(["sh", "-c", command],
                                         Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error:
            self._command_done(command, False)
            return
        self.command_running.add(command)
        # A command that hangs counts as failed and is stopped.
        timeout = GLib.timeout_add_seconds(led_rules.COMMAND_TIMEOUT, lambda: process.force_exit() or False)

        def finished(proc, result):
            GLib.source_remove(timeout)
            try:
                proc.wait_finish(result)
                ok = proc.get_if_exited() and proc.get_exit_status() == 0
            except GLib.Error:
                ok = False
            self.command_running.discard(command)
            self._command_done(command, ok)
        process.wait_async(None, finished)

    def _command_done(self, command, ok):
        changed = self.command_results.get(command) != ok
        self.command_results[command] = ok
        if changed:
            self.evaluate()

    def _screensaver_changed(self, _bus, _sender, _path, _iface, _signal, params):
        if not params.unpack()[0]:  # the shield went away: someone is looking
            self.pending.clear()
            self.evaluate()

    def _idle_ms(self):
        if self.bus is None:
            return None
        try:
            reply = self.bus.call_sync("org.gnome.Mutter.IdleMonitor", "/org/gnome/Mutter/IdleMonitor/Core",
                                       "org.gnome.Mutter.IdleMonitor", "GetIdletime", None,
                                       GLib.VariantType.new("(t)"), Gio.DBusCallFlags.NONE, 500, None)
            return reply.unpack()[0]
        except GLib.Error:
            return None

    def _expire_seen(self):
        idle = self._idle_ms()
        if idle is None or not self.pending:
            return
        now = time.monotonic()
        # Seen = there was input after it arrived (two seconds of grace for
        # the very event that produced it, such as a sent message).
        self.pending = [(when, sources) for when, sources in self.pending
                        if idle / 1000 >= now - when - 2]

    def _media_playing(self):
        if self.bus is None:
            return False
        try:
            names = self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                       "ListNames", None, None, Gio.DBusCallFlags.NONE, 500, None).unpack()[0]
            for name in names:
                if not name.startswith("org.mpris.MediaPlayer2."):
                    continue
                status = self.bus.call_sync(name, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties",
                                            "Get", GLib.Variant("(ss)", ("org.mpris.MediaPlayer2.Player",
                                                                         "PlaybackStatus")),
                                            None, Gio.DBusCallFlags.NONE, 500, None).unpack()[0]
                if status == "Playing":
                    return True
        except GLib.Error:
            pass
        return False

    def status(self, rules):
        status = power_status()
        status["notifications"] = [sources for _when, sources in self.pending]
        status["signals"] = set(self.signals)
        self._run_commands(rules)
        status["commands"] = dict(self.command_results)
        if any(rule["condition"] == "media" and rule["enabled"] for rule in rules):
            status["media"] = self._media_playing()
        return status

    # -- decision -------------------------------------------------------------

    def wanted(self):
        if not self.settings.get_boolean("led-enabled"):
            return ("restore",)
        if self.preview is not None:
            rule = self.preview
        else:
            if self.settings.get_boolean("led-quiet-enabled") and led_rules.in_quiet_hours(
                    time.localtime().tm_hour, self.settings.get_int("led-quiet-start"),
                    self.settings.get_int("led-quiet-end")):
                return ("off",)
            self._expire_seen()
            rules = led_rules.usable(led_rules.load(self.settings.get_string("led-rules")),
                                     self.settings.get_boolean("led-advanced"))
            rule = led_rules.choose(rules, self.status(rules))
        if rule is None:
            return ("off",)
        brightness = min(100, max(1, self.settings.get_int("led-brightness")))
        return ("show", rule["effect"], rule["color"], str(brightness))

    def evaluate(self):
        self._apply(self.wanted())
        return False

    def _tick(self):
        self.evaluate()
        return True

    def show_preview(self, rule):
        """Shows `rule` for PREVIEW_SECONDS; None ends the preview now."""
        self.preview = led_rules.clean(rule) if rule is not None else None
        if self.preview_timer is not None:
            GLib.source_remove(self.preview_timer)
            self.preview_timer = None
        if self.preview is None:
            self.evaluate()
            return

        def done():
            self.preview, self.preview_timer = None, None
            self.evaluate()
            return False
        self.preview_timer = GLib.timeout_add_seconds(PREVIEW_SECONDS, done)
        self.evaluate()

    # -- output ---------------------------------------------------------------

    def _apply(self, wanted):
        if wanted == self.shown and not self.busy:
            return
        if self.busy:
            self.queued = wanted
            return
        self.busy = True
        self.run(wanted, self._applied)

    def _applied(self, wanted, ok):
        self.busy = False
        if ok:
            self.shown = wanted
        queued, self.queued = self.queued, None
        if queued is not None and queued != self.shown:
            self._apply(queued)

    @staticmethod
    def argv(wanted):
        return ["pkexec", HELPER, *wanted]

    def _spawn(self, wanted, done):
        try:
            process = Gio.Subprocess.new(self.argv(wanted), Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error:
            done(wanted, False)
            return
        state = {"answered": False}

        def finish(ok):
            if not state["answered"]:
                state["answered"] = True
                done(wanted, ok)

        def exited(proc, result):
            if not state["answered"]:
                GLib.source_remove(state["timeout"])
            finish(self._finished(proc, result))

        def timed_out():
            # A helper stuck in the kernel (a broken LED driver) must not
            # keep every later change waiting behind it.
            process.force_exit()
            finish(False)
            return False
        state["timeout"] = GLib.timeout_add_seconds(HELPER_TIMEOUT, timed_out)
        process.wait_check_async(None, exited)

    @staticmethod
    def _finished(process, result):
        try:
            return process.wait_check_finish(result)
        except GLib.Error:
            return False

    def close(self):
        GLib.source_remove(self.timer)
        if self.shown is not None and self.shown != ("restore",):
            try:
                Gio.Subprocess.new(["pkexec", HELPER, "restore"], Gio.SubprocessFlags.NONE).wait(None)
            except GLib.Error:
                pass
