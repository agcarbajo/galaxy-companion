# SPDX-License-Identifier: MIT
"""Home page: which device this is, and updates of Galaxy Companion itself."""
import threading

from gi.repository import Adw, Gio, GLib, Gtk

from . import app_update
from . import system_summary
from . import update_bundle
from .i18n import _

FORM_FACTOR_ICONS = {
    "tablet": "galaxy-companion-tablet",
    "phone": "galaxy-companion-phone",
    "foldable": "galaxy-companion-foldable",
}


def info_row(title, value):
    row = Adw.ActionRow(title=title)
    # One line while it fits; a long SoC name wraps instead of widening the row.
    label = Gtk.Label(label=value, selectable=True, wrap=True, natural_wrap_mode=Gtk.NaturalWrapMode.NONE,
                      xalign=1, justify=Gtk.Justification.RIGHT, css_classes=["dim-label"])
    row.add_suffix(label)
    return row


class HomePage(Adw.PreferencesPage):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.busy = False
        self.info = None
        self.package = None
        self.installed = None
        device = window.device
        self.set_margin_top(18)
        self.set_margin_bottom(18)

        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, halign=Gtk.Align.CENTER)
        icon = Gtk.Image(icon_name=FORM_FACTOR_ICONS.get(device.form_factor, FORM_FACTOR_ICONS["phone"]),
                         pixel_size=160, margin_bottom=12)
        icon.update_property([Gtk.AccessibleProperty.LABEL], [{
            "tablet": _("Tablet"), "phone": _("Phone"), "foldable": _("Foldable"),
        }.get(device.form_factor, _("Phone"))])
        hero.append(icon)
        hero.append(Gtk.Label(label=device.name, wrap=True, justify=Gtk.Justification.CENTER,
                              css_classes=["title-1"]))
        if device.model:
            hero.append(Gtk.Label(label=device.model, css_classes=["title-4", "dim-label"]))
        top = Adw.PreferencesGroup()
        top.add(hero)
        self.add(top)

        details = Adw.PreferencesGroup()
        unknown = _("Unknown")
        details.add(info_row(_("Processor"), system_summary.processor() or unknown))
        details.add(info_row(_("Memory"), system_summary.marketed_memory(system_summary.memory_kib()) or unknown))
        system = system_summary.os_release().get("PRETTY_NAME")
        if system:
            details.add(info_row(_("System"), system))
        self.add(details)

        updates = Adw.PreferencesGroup()
        self.update_row = Adw.ActionRow(title="Galaxy Companion")
        self.update_spinner = Gtk.Spinner(valign=Gtk.Align.CENTER, visible=False)
        self.update_button = Gtk.Button(valign=Gtk.Align.CENTER)
        self.update_button.connect("clicked", self._update_clicked)
        self.update_row.add_suffix(self.update_spinner)
        self.update_row.add_suffix(self.update_button)
        updates.add(self.update_row)
        # On a port with system updates the switch lives on that page and
        # covers both; elsewhere this is the only place it can be turned on.
        if not update_bundle.supported():
            weekly = Adw.SwitchRow(title=_("Check for updates weekly"),
                                   subtitle=_("Notify me when a new version of Galaxy Companion is available."))
            window.settings.bind("weekly-update-checks", weekly, "active", Gio.SettingsBindFlags.DEFAULT)
            weekly.connect("notify::active", self._weekly_changed)
            updates.add(weekly)
        self.add(updates)
        self._idle(app_update.installed())

    def show_empty_note(self):
        """Explain an otherwise lonely home page: there is nothing else to show."""
        self.add(Adw.PreferencesGroup(description=_(
            "Galaxy Companion did not find an S Pen, a keyboard cover, a vibration "
            "motor or a fingerprint reader on this {device}. A device profile can "
            "describe the hardware it cannot find on its own."
        ).format(device=self.window.device.name)))

    # -- Galaxy Companion updates ------------------------------------------

    def _button(self, label, action, suggested=False):
        self.update_button.set_label(label)
        self.update_button.set_css_classes(["suggested-action"] if suggested else [])
        self.update_button.set_sensitive(True)
        self.update_button.set_visible(True)
        self._action = action

    def _working(self, subtitle):
        self.busy = True
        self.update_row.set_subtitle(subtitle)
        self.update_button.set_visible(False)
        self.update_spinner.set_visible(True)
        self.update_spinner.start()

    def _done(self):
        self.busy = False
        self.update_spinner.stop()
        self.update_spinner.set_visible(False)

    def _idle(self, version, subtitle=None):
        self.update_row.set_subtitle(subtitle or _("Version {version}").format(
            version=app_update.shown_version(version)))
        self._button(_("Check for Updates"), self._check)

    def _update_clicked(self, _button):
        self._action()

    def _background(self, work, finished):
        def worker():
            try:
                result, error = work(), None
            except Exception as exc:  # network, TLS, malformed release
                result, error = None, str(exc)
            GLib.idle_add(finished, result, error)
        threading.Thread(target=worker, daemon=True).start()

    def _check(self):
        self._working(_("Checking for updates…"))
        self._background(lambda: (app_update.check(), app_update.installed()), self._checked)

    def checked(self, info, available):
        """A result from elsewhere (the weekly check); ignored while busy."""
        if not self.busy:
            self._checked(((info, available), app_update.installed()), None)

    def _checked(self, result, error):
        self._done()
        if error:
            self._idle(app_update.installed(), _("Couldn't check for updates"))
            return False
        (info, available), installed = result
        if available:
            self.info = info
            self.update_row.set_subtitle(_("Version {version} is available").format(version=info["version"]))
            self._button(_("Update"), self._download, suggested=True)
        else:
            self._idle(installed, _("Version {version} · Up to date").format(
                version=app_update.shown_version(installed)))
        return False

    def _download(self):
        info = self.info
        self._working(_("Downloading version {version}…").format(version=info["version"]))
        self._background(lambda: app_update.download(info), self._downloaded)

    def _downloaded(self, path, error):
        if error:
            self._done()
            self.update_row.set_subtitle(_("Couldn't download the update"))
            self._button(_("Try Again"), self._download, suggested=True)
            return False
        self.package = path
        self._working(_("Installing version {version}…").format(version=self.info["version"]))
        self._background(lambda: app_update.install(path, self.info["sha256"]), self._installed)
        return False

    def _installed(self, result, error):
        self._done()
        ok, message = result if result else (False, error)
        if not ok:
            self.update_row.set_subtitle(_("The update was cancelled") if message == "cancelled"
                                         else _("Couldn't install the update"))
            self._button(_("Try Again"), self._download, suggested=True)
            return False
        self.update_row.set_subtitle(_("Version {version} is installed. Restart Galaxy Companion to use it.")
                                     .format(version=self.info["version"]))
        self._button(_("Restart"), self._restart, suggested=True)
        return False

    def _weekly_changed(self, row, *_args):
        if row.get_active():
            try:
                Gio.Subprocess.new(["/usr/libexec/galaxy-companion-update-schedule"], Gio.SubprocessFlags.NONE)
            except GLib.Error:
                pass
        elif self.window.get_application():
            self.window.get_application().withdraw_notification("app-update")

    def _restart(self):
        # The session backend runs the old code until it restarts too.
        for argv in (["systemctl", "--user", "try-restart", "galaxy-companion-hardware.service"],
                     ["sh", "-c", "sleep 1; exec galaxy-companion"]):
            try:
                Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE)
            except GLib.Error:
                pass
        self.window.get_application().quit()
