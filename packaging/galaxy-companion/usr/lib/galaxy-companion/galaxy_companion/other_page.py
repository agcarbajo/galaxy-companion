# SPDX-License-Identifier: MIT
"""Settings that fit no other page.  The page exists only when one applies."""
from gi.repository import Adw, Gio, GLib, Gtk

from . import charge_limit
from .i18n import _

CHARGE_HELPER = "/usr/libexec/galaxy-companion-charge-limit"


def has_options():
    return charge_limit.available()


class OtherPage(Adw.PreferencesPage):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.set_margin_top(18)
        self.set_margin_bottom(18)
        if charge_limit.available():
            self.add(self._battery_group())

    # -- battery charge limit --------------------------------------------------

    def _battery_group(self):
        group = Adw.PreferencesGroup(title=_("Battery"), description=_(
            "Keeping the battery below a full charge makes it last longer, which helps "
            "a device that stays plugged in most of the time."))
        state = charge_limit.load()
        self.levels = charge_limit.levels()
        self._applying = False
        self.limit_switch = Adw.SwitchRow(title=_("Limit charging"), active=state["enabled"],
                                          subtitle=_("Stop charging at the level below"))
        self.limit_level = Adw.ComboRow(title=_("Charge up to"), model=Gtk.StringList.new(
            [f"{level} %" for level in self.levels]), sensitive=state["enabled"])
        self.limit_level.set_selected(self.levels.index(state["limit"]))
        level = charge_limit.battery_level()
        if level is not None:
            self.limit_level.set_subtitle(_("The battery is at {percent} %").format(percent=level))
        self.limit_switch.connect("notify::active", self._limit_changed)
        self.limit_level.connect("notify::selected", self._limit_changed)
        group.add(self.limit_switch)
        group.add(self.limit_level)
        return group

    def _limit_changed(self, *_args):
        if self._applying:
            return
        enabled = self.limit_switch.get_active()
        limit = self.levels[self.limit_level.get_selected()]
        self.limit_level.set_sensitive(enabled)
        try:
            process = Gio.Subprocess.new(["pkexec", CHARGE_HELPER, "set", "on" if enabled else "off", str(limit)],
                                         Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error:
            self._restore()
            return
        process.wait_check_async(None, self._limit_applied)

    def _limit_applied(self, process, result):
        try:
            process.wait_check_finish(result)
        except GLib.Error:
            self._restore()

    def _restore(self):
        """Show what is really in effect after a refused or failed change."""
        state = charge_limit.load()
        self._applying = True
        self.limit_switch.set_active(state["enabled"])
        self.limit_level.set_selected(self.levels.index(state["limit"]))
        self.limit_level.set_sensitive(state["enabled"])
        self.limit_level.set_subtitle(_("Couldn't change the charge limit"))
        self._applying = False
