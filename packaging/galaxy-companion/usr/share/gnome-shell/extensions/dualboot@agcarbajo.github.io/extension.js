// SPDX-License-Identifier: MIT
//
// A quick settings entry that restarts the device into the other system.
//
// It owns no logic of its own: the same two libexec helpers the Galaxy Companion
// window uses do the reading and the writing, behind the same polkit rules.
// So the toggle cannot do anything the app cannot, and the password prompt
// that polkit raises is the confirmation step.

import GObject from 'gi://GObject';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import {QuickToggle, SystemIndicator} from 'resource:///org/gnome/shell/ui/quickSettings.js';

const STATUS_HELPER = '/usr/libexec/galaxy-companion-boot-status';
const SWITCH_HELPER = '/usr/libexec/galaxy-companion-boot-switch';

// GJS does not hand out promises for async GIO methods until they are
// promisified.  Without this, `await proc.communicate_utf8_async(null, null)`
// throws "At least 3 arguments required, but only 2 passed", the refresh dies,
// and the toggle stays hidden forever with no visible symptom.
Gio._promisify(Gio.Subprocess.prototype, 'communicate_utf8_async');

// The same built-in catalogue the app uses, for the same reason: shipping .mo
// files for three visible strings is more machinery than it is worth, and this
// keeps the extension translated without a build step.
const CATALOGUE = {
    'Dual boot': {
        es: 'Arranque dual', fr: 'Double démarrage', de: 'Dual-Boot',
        it: 'Avvio doppio', pt: 'Arranque duplo',
    },
    'Writing the boot partitions…': {
        es: 'Escribiendo las particiones de arranque…',
        fr: 'Écriture des partitions de démarrage…',
        de: 'Boot-Partitionen werden geschrieben…',
        it: 'Scrittura delle partizioni di avvio…',
        pt: 'A escrever as partições de arranque…',
    },
    'The system was not changed.': {
        es: 'No se ha cambiado de sistema.',
        fr: 'Le système n’a pas été changé.',
        de: 'Das System wurde nicht gewechselt.',
        it: 'Il sistema non è stato cambiato.',
        pt: 'O sistema não foi alterado.',
    },
};

// The language the desktop shows, not just the locale: a system set to
// es_ES without GNOME's Spanish translations shows English, and so does this
// toggle. The first wanted language that gnome-shell has a catalogue for and
// CATALOGUE knows wins (as Galaxy Companion's app decides); English otherwise.
function desktopLanguage() {
    const known = new Set(Object.values(CATALOGUE).flatMap(Object.keys));
    const dirs = ['/usr/share/locale', '/usr/share/locale-langpack'];
    // gettext ignores LANGUAGE under the C locale; GLib's list does not
    const main = GLib.getenv('LC_ALL') || GLib.getenv('LC_MESSAGES') || GLib.getenv('LANG') || 'C';
    if (main === 'C' || main === 'POSIX' || main.startsWith('C.'))
        return 'en';
    for (const name of GLib.get_language_names_with_category('LC_MESSAGES')) {
        if (name === 'C' || name === 'POSIX' || name.startsWith('C.'))
            break;
        const code = name.split(/[_.@-]/)[0].toLowerCase();
        if (code === 'en')
            return 'en';
        if (known.has(code) && dirs.some(dir => GLib.file_test(
            `${dir}/${name}/LC_MESSAGES/gnome-shell.mo`, GLib.FileTest.EXISTS)))
            return code;
    }
    return 'en';
}

const LANG = desktopLanguage();

function _(message) {
    return CATALOGUE[message]?.[LANG] ?? message;
}

const DualBootToggle = GObject.registerClass(
class DualBootToggle extends QuickToggle {
    _init() {
        super._init({
            title: _('Dual boot'),
            iconName: 'drive-multidisk-symbolic',
            // A button, not a state: pressing it reboots, and there is nothing
            // to leave switched on afterwards.
            toggleMode: false,
        });

        this._target = null;
        this._busy = false;
        this.visible = false;

        this.connect('clicked', () => this._switch());
        this._refresh();
    }

    async _run(argv, cancellable = null) {
        const proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
        // Promisified, this resolves to [stdout, stderr] — verified on the
        // tablet rather than assumed, because reading the wrong element gives
        // an empty string and looks exactly like a command that printed
        // nothing.
        const [stdout] = await proc.communicate_utf8_async(null, cancellable);
        return {ok: proc.get_successful(), stdout: stdout ?? ''};
    }

    async _refresh() {
        try {
            const {ok, stdout} = await this._run(['pkexec', STATUS_HELPER]);
            if (!ok)
                return;

            const status = JSON.parse(stdout);
            const others = (status.sets ?? []).filter(s => s.id !== status.current && s.complete);

            // With one system there is nothing to switch to, so the toggle
            // stays out of the menu entirely rather than sitting there dead.
            if (others.length === 0) {
                this.visible = false;
                this._target = null;
                return;
            }

            this._target = others[0];
            this.subtitle = this._target.label;
            this.visible = true;
        } catch (error) {
            logError(error, 'dualboot: could not read the current system');
        }
    }

    async _switch() {
        if (this._busy || !this._target)
            return;
        this._busy = true;
        this.checked = true;

        try {
            Main.notify(_('Dual boot'), _('Writing the boot partitions…'));
            const {ok} = await this._run(['pkexec', SWITCH_HELPER, this._target.id, '--reboot']);
            if (!ok)
                Main.notifyError(_('Dual boot'), _('The system was not changed.'));
        } catch (error) {
            logError(error, 'dualboot: switch failed');
        } finally {
            this._busy = false;
            this.checked = false;
        }
    }
});

const DualBootIndicator = GObject.registerClass(
class DualBootIndicator extends SystemIndicator {
    _init() {
        super._init();
        this._toggle = new DualBootToggle();
        this.quickSettingsItems.push(this._toggle);
    }
});

export default class DualBootExtension extends Extension {
    enable() {
        this._indicator = new DualBootIndicator();
        Main.panel.statusArea.quickSettings.addExternalIndicator(this._indicator);
    }

    disable() {
        this._indicator?.quickSettingsItems.forEach(item => item.destroy());
        this._indicator?.destroy();
        this._indicator = null;
    }
}
