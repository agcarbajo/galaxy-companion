# SPDX-License-Identifier: MIT

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import sys
import threading
from gi.repository import Adw, Gio, GLib

from . import APP_ID, VERSION
from .window import CompanionWindow
from . import app_update, update_bundle, update_monitor
from .i18n import _


class CompanionApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.connect("activate", self._activate)
        self.connect("command-line", self._command_line)
        home = Gio.SimpleAction.new("open-home", None)
        home.connect("activate", self._open_home)
        self.add_action(home)
        action = Gio.SimpleAction.new("open-updates", None)
        action.connect("activate", self._open_updates)
        self.add_action(action)
        check = Gio.SimpleAction.new("check-updates", None)
        check.connect("activate", lambda *_: self._weekly_check())
        self.add_action(check)
        self._checking_updates = False

    def _command_line(self, _app, command):
        args = command.get_arguments()[1:]
        if "--check-updates" in args:
            self._weekly_check()
        elif "--updates" in args:
            self._open_updates()
        else:
            self.activate()
        return 0

    def _open_updates(self, *_args):
        self.activate()
        window = self.props.active_window
        if window.update_page is not None:
            window.view_stack.set_visible_child_name("updates")

    def _open_home(self, *_args):
        self.activate()
        self.props.active_window.view_stack.set_visible_child_name("home")

    def _weekly_check(self):
        settings = Gio.Settings.new(APP_ID)
        if settings.get_boolean("weekly-update-checks") and app_update.due():
            self._weekly_app_check()
        if (self._checking_updates or not update_bundle.supported() or not settings.get_boolean("weekly-update-checks")
                or not update_monitor.due(update_monitor.load())):
            return
        self._checking_updates = True
        self.hold()
        def worker():
            try:
                info, error = update_bundle.release(), None
            except Exception as exc:
                info, error = None, str(exc)
            GLib.idle_add(self._weekly_result, info, error)
        threading.Thread(target=worker, daemon=True).start()

    def _weekly_result(self, info, error):
        try:
            # The preference may have changed while the network request ran.
            if info and Gio.Settings.new(APP_ID).get_boolean("weekly-update-checks"):
                value, key = update_monitor.record(info, notify=True)
                if key:
                    notification = Gio.Notification.new(_("Update available"))
                    notification.set_body(_("Build {version} is available. Open Galaxy Companion to review it.").format(version=info["tag"]))
                    notification.set_icon(Gio.ThemedIcon.new("software-update-available-symbolic"))
                    notification.set_default_action("app.open-updates")
                    self.send_notification("system-update", notification)
                    update_monitor.notified(key)
                elif not update_monitor.available(value):
                    self.withdraw_notification("system-update")
                window = self.props.active_window
                if window and window.update_page is not None:
                    window.refresh_update_badge()
                    if not window.update_page.busy:
                        window.update_page._checked(info, None)
        finally:
            self._checking_updates = False
            self.release()
        return False

    def _weekly_app_check(self):
        """Galaxy Companion's own releases, on every device, port or not."""
        self.hold()
        def worker():
            try:
                result = app_update.check()
            except Exception:
                result = None  # offline: try again next time, quietly
            GLib.idle_add(self._weekly_app_result, result)
        threading.Thread(target=worker, daemon=True).start()

    def _weekly_app_result(self, result):
        try:
            if result:
                info, available = result
                if app_update.record(info, available):
                    notification = Gio.Notification.new(_("Galaxy Companion update available"))
                    notification.set_body(_("Version {version} is available.").format(version=info["version"]))
                    notification.set_icon(Gio.ThemedIcon.new("software-update-available-symbolic"))
                    notification.set_default_action("app.open-home")
                    self.send_notification("app-update", notification)
                window = self.props.active_window
                if window is not None:
                    window.home_page.checked(info, available)
        finally:
            self.release()
        return False

    def _activate(self, _app):
        window = self.props.active_window
        if window is None:
            window = CompanionWindow(self)
        window.present()


def led_signal(args):
    """`galaxy-companion --led-signal NAME on|off`: for scripts, no window.

    Talks to the session backend, which owns the LED rules; D-Bus starts it
    if it is not running yet.
    """
    from . import led_rules
    if len(args) != 2 or args[1] not in ("on", "off") or not led_rules.SIGNAL.match(args[0]):
        print("usage: galaxy-companion --led-signal NAME on|off   (NAME: letters, digits, - and _)",
              file=sys.stderr)
        return 2
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        accepted = bus.call_sync(
            "io.github.agcarbajo.GalaxyCompanion.Hardware", "/io/github/agcarbajo/GalaxyCompanion/Hardware",
            "io.github.agcarbajo.GalaxyCompanion.Hardware", "SetLedSignal",
            GLib.Variant("(sb)", (args[0], args[1] == "on")), GLib.VariantType.new("(b)"),
            Gio.DBusCallFlags.NONE, 10000, None).unpack()[0]
    except GLib.Error as error:
        print(f"galaxy-companion: {error.message}", file=sys.stderr)
        return 1
    if not accepted:
        print("galaxy-companion: this device has no status LED", file=sys.stderr)
        return 1
    return 0


def main(argv):
    if argv[1:2] == ["--led-signal"]:
        return led_signal(argv[2:])
    return CompanionApplication().run(argv)
