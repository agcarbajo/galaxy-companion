# SPDX-License-Identifier: MIT
"""About → Troubleshooting: restart every GNOME Shell extension."""
import json

from gi.repository import Adw, Gio, GLib, Gtk

from . import shell_extensions
from .i18n import _
from .keyboard_diagnostics_ui import message, troubleshooting_group

HELPER = "/usr/libexec/galaxy-companion-shell-extensions"


def add_to_about(about):
    if not shell_extensions.available():
        return None
    group = troubleshooting_group(about)
    if group is None:
        return None
    row = Adw.ActionRow(title=_("Restart desktop extensions"),
        subtitle=_("Turn them back on and reload them if the dock, quick settings or other extensions stopped working."),
        activatable=True)
    row.add_suffix(Gtk.Image(icon_name="view-refresh-symbolic"))
    row.connect("activated", lambda *_args: restart(about, row))
    group.add(row)
    return row


def show_result(parent, output, error):
    """Say what happened, from the helper's output or its error."""
    if error is not None:
        message(parent, _("Could not restart extensions"), error)
        return
    failed = json.loads(output).get("failed", [])
    if failed:
        message(parent, _("Some extensions did not restart"),
                _("Log out and back in to start these: {names}").format(names=", ".join(failed)))
    else:
        message(parent, _("Extensions restarted"), _("All extensions are running again."))


def restart(parent, row):
    row.set_sensitive(False)
    def finished(process, result):
        row.set_sensitive(True)
        try:
            _ok, output, errors = process.communicate_utf8_finish(result)
            if not process.get_successful():
                show_result(parent, None, (errors or "").strip() or _("Could not restart extensions"))
                return
            show_result(parent, output, None)
        except (GLib.Error, ValueError) as error:
            show_result(parent, None, str(error))
    try:
        process = Gio.Subprocess.new([HELPER, "restart"],
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)
        process.communicate_utf8_async(None, None, finished)
    except GLib.Error as error:
        row.set_sensitive(True)
        show_result(parent, None, error.message)
