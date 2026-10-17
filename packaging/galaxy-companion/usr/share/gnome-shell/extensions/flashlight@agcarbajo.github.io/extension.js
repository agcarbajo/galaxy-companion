// SPDX-License-Identifier: MIT
//
// A quick settings toggle for the device's torch, with a brightness slider.
//
// Galaxy Companion's helper does the switching, as for button actions; it
// also says which LED the device profile names, so nothing here is tied to a
// device. Without a torch the helper fails and no toggle is added. (Started
// from the Galaxy Tab S9 Ultra port's own flashlight extension.)

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as QuickSettings from 'resource:///org/gnome/shell/ui/quickSettings.js';
import {Slider} from 'resource:///org/gnome/shell/ui/slider.js';

const HELPER = '/usr/libexec/galaxy-companion-flashlight';
const SCHEMA = 'io.github.agcarbajo.GalaxyCompanion.Flashlight';
const ICON = 'camera-flash-symbolic';

// The same built-in catalogue the app uses (see the dual boot extension).
const CATALOGUE = {
    'Flashlight': {es: 'Linterna', fr: 'Lampe torche', de: 'Taschenlampe', it: 'Torcia', pt: 'Lanterna'},
};
const LANG = (GLib.getenv('LANGUAGE') || GLib.getenv('LC_ALL') ||
    GLib.getenv('LC_MESSAGES') || GLib.getenv('LANG') || 'en')
    .split(':')[0].split('_')[0].split('-')[0].toLowerCase();

function _(message) {
    return CATALOGUE[message]?.[LANG] ?? message;
}

// The torch's sysfs directory, or null when the device has none.
// GJS always collects stderr, so no STDERR_TO_DEV_NULL here: with it
// g_spawn_sync() refuses to run and the tile silently went missing.
function ledDirectory() {
    try {
        const [ok, out, err, status] = GLib.spawn_sync(null, [HELPER, 'path'], null,
            GLib.SpawnFlags.DEFAULT, null);
        if (!ok || status !== 0) {
            const reason = err ? new TextDecoder().decode(err).trim() : '';
            console.log(`Flashlight: no toggle: ${reason || `${HELPER} failed`}`);
            return null;
        }
        return new TextDecoder().decode(out).trim() || null;
    } catch (error) {
        console.log(`Flashlight: no toggle: ${error.message}`);
        return null;
    }
}

function readNumber(path) {
    try {
        const [, contents] = Gio.File.new_for_path(path).load_contents(null);
        return Number(new TextDecoder().decode(contents).trim());
    } catch (error) {
        console.error(`Flashlight: cannot read ${path}: ${error.message}`);
        return NaN;
    }
}

// The schema ships with Galaxy Companion; the tile still works without it.
function openSettings() {
    const source = Gio.SettingsSchemaSource.get_default();
    if (!source?.lookup(SCHEMA, true))
        return null;
    return new Gio.Settings({schema_id: SCHEMA});
}

const BrightnessItem = GObject.registerClass(
class BrightnessItem extends PopupMenu.PopupBaseMenuItem {
    constructor(onChange) {
        super({activate: false});

        this._onChange = onChange;
        this._updating = false;

        this.add_child(new St.Icon({style_class: 'popup-menu-icon', icon_name: ICON}));

        this._slider = new Slider(0);
        this._slider.x_expand = true;
        this._slider.connect('notify::value', () => {
            if (!this._updating)
                this._onChange(this.level);
        });
        this.add_child(this._slider);

        // The row is the slider, as with the sound and display sliders.
        this.connect('key-press-event',
            (actor, event) => this._slider.emit('key-press-event', event));
    }

    // Levels are on the helper's 1-255 scale.
    get level() {
        return Math.max(1, Math.round(this._slider.value * 255));
    }

    setLevel(level) {
        this._updating = true;
        this._slider.value = Math.min(1, Math.max(0, level / 255));
        this._updating = false;
    }
});

const FlashlightToggle = GObject.registerClass(
class FlashlightToggle extends QuickSettings.QuickMenuToggle {
    constructor(settings, directory) {
        super({title: _('Flashlight'), iconName: ICON, toggleMode: true});

        this._settings = settings;
        this._brightnessPath = `${directory}/brightness`;
        const maximum = readNumber(`${directory}/max_brightness`);
        this._maximum = Number.isFinite(maximum) && maximum > 0 ? maximum : 255;
        this._syncing = false;

        this.menu.setHeader(ICON, _('Flashlight'));
        this._brightness = new BrightnessItem(level => this._setLevel(level));
        this.menu.addMenuItem(this._brightness);

        this._checkedId = this.connect('notify::checked', () => {
            if (!this._syncing)
                this._apply(this.checked);
        });

        // A button action may switch the LED without this tile; it says so
        // here, and the LED is read back rather than trusted.
        this._settingsId = this._settings?.connect(
            'changed::on', () => this.syncFromHardware());

        this.syncFromHardware();
    }

    get _level() {
        return Math.min(255, Math.max(1, this._settings?.get_int('brightness') ?? 128));
    }

    syncFromHardware() {
        const raw = readNumber(this._brightnessPath);
        const lit = Number.isFinite(raw) && raw > 0;
        const level = lit ? Math.round(raw * 255 / this._maximum) : this._level;
        this._syncing = true;
        this.checked = lit;
        this._syncing = false;
        this._brightness.setLevel(level);
        this.subtitle = lit ? `${Math.round(100 * level / 255)}%` : null;
    }

    _setLevel(level) {
        this._settings?.set_int('brightness', level);
        if (this.checked)
            this._apply(true, level);
    }

    _apply(enabled, level = this._level) {
        const argv = enabled ? [HELPER, 'on', String(level)] : [HELPER, 'off'];
        let process;
        try {
            process = Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE);
        } catch (error) {
            console.error(`Flashlight: ${error.message}`);
            this.syncFromHardware();
            return;
        }
        process.wait_check_async(null, (source, result) => {
            try {
                source.wait_check_finish(result);
                this._settings?.set_boolean('on', enabled);
                this.subtitle = enabled ? `${Math.round(100 * level / 255)}%` : null;
            } catch (error) {
                console.error(`Flashlight: ${error.message}`);
                this.syncFromHardware();
            }
        });
    }

    turnOff() {
        try {
            Gio.Subprocess.new([HELPER, 'off'], Gio.SubprocessFlags.NONE);
            this._settings?.set_boolean('on', false);
        } catch (error) {
            console.error(`Flashlight: ${error.message}`);
        }
    }

    destroy() {
        if (this._checkedId) {
            this.disconnect(this._checkedId);
            this._checkedId = 0;
        }
        if (this._settingsId) {
            this._settings.disconnect(this._settingsId);
            this._settingsId = 0;
        }
        super.destroy();
    }
});

const FlashlightIndicator = GObject.registerClass(
class FlashlightIndicator extends QuickSettings.SystemIndicator {
    constructor(settings, directory) {
        super();

        this._toggle = new FlashlightToggle(settings, directory);
        this.quickSettingsItems.push(this._toggle);

        // The status icon follows the toggle, which follows the LED.
        this._indicator = this._addIndicator();
        this._indicator.icon_name = ICON;
        this._indicator.visible = this._toggle.checked;
        this._checkedId = this._toggle.connect('notify::checked', () => {
            this._indicator.visible = this._toggle.checked;
        });
    }

    destroy() {
        // Locking the screen disables extensions: no torch left on behind it.
        this._toggle.turnOff();
        if (this._checkedId) {
            this._toggle.disconnect(this._checkedId);
            this._checkedId = 0;
        }
        this.quickSettingsItems.forEach(item => item.destroy());
        super.destroy();
    }
});

export default class FlashlightExtension extends Extension {
    enable() {
        const directory = ledDirectory();
        if (!directory)
            return;
        this._indicator = new FlashlightIndicator(openSettings(), directory);
        Main.panel.statusArea.quickSettings.addExternalIndicator(this._indicator);
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
