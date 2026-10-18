// SPDX-License-Identifier: MIT
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const BUS_NAME = 'io.github.agcarbajo.GalaxyCompanion.KeyboardFeedback';
const OBJECT_PATH = '/io/github/agcarbajo/GalaxyCompanion/KeyboardFeedback';

export default class GalaxyCompanionHaptics extends Extension {
    enable() {
        this._settings = new Gio.Settings({
            schema_id: 'io.github.agcarbajo.GalaxyCompanion',
        });
        this._proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SYSTEM,
            Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
            null,
            BUS_NAME,
            OBJECT_PATH,
            BUS_NAME,
            null
        );
        this._settingsIds = [
            'keyboard-haptics-enabled', 'keyboard-haptics-strength',
        ].map(key => this._settings.connect(`changed::${key}`,
            () => this._syncPreferences()));
        this._ownerId = this._proxy.connect('notify::g-name-owner',
            () => this._syncPreferences());
        this._syncPreferences();
        this._actors = new Map();
        this._visibilityId = Main.keyboard.connect('visibility-changed',
            () => this._watchKeyboard());
        this._watchKeyboard();
    }

    disable() {
        if (this._visibilityId)
            Main.keyboard.disconnect(this._visibilityId);
        this._visibilityId = 0;
        for (const [actor, ids] of this._actors ?? [])
            for (const id of ids)
                actor.disconnect(id);
        this._actors?.clear();
        for (const id of this._settingsIds ?? [])
            this._settings.disconnect(id);
        this._settingsIds = [];
        if (this._ownerId)
            this._proxy.disconnect(this._ownerId);
        this._ownerId = 0;
        this._proxy = null;
        this._settings = null;
    }

    _syncPreferences() {
        // GDM has its own dconf database. Only the user's Shell may update
        // the saved preference; the greeter uses that same enabled flag.
        if (Main.sessionMode.isGreeter)
            return;
        this._proxy.call('SetPreferences', new GLib.Variant('(bu)', [
            this._settings.get_boolean('keyboard-haptics-enabled'),
            Math.max(1, Math.min(3, this._settings.get_int('keyboard-haptics-strength'))),
        ]), Gio.DBusCallFlags.NONE, 1000, null, (proxy, result) => {
            try { proxy.call_finish(result); } catch (_) { /* Retry on owner change. */ }
        });
    }

    _watchKeyboard() {
        const keyboard = Main.keyboard.keyboardActor;
        if (keyboard)
            this._watchActor(keyboard);
    }

    _watchActor(actor) {
        if (this._actors.has(actor))
            return;
        const ids = [];
        this._actors.set(actor, ids);
        ids.push(actor.connect('destroy', () => this._actors.delete(actor)));
        const type = actor.constructor.$gtype;
        // Use the OSK's own activation signal. Stage touch hit-testing is
        // affected by modal grabs in lock/authentication dialogs, and misses
        // pointer activation. No key identity or entered text is inspected.
        if (actor.has_style_class_name?.('key-container') &&
            GObject.signal_lookup('pressed', type))
            ids.push(actor.connect('pressed', () => this._pulse()));
        const added = ['child-added', 'actor-added'].find(
            signal => GObject.signal_lookup(signal, type));
        if (added)
            ids.push(actor.connect(added, (_parent, child) => this._watchActor(child)));
        for (const child of actor.get_children())
            this._watchActor(child);
    }

    _pulse() {
        if (!Main.keyboard.visible ||
            (!Main.sessionMode.isGreeter &&
             !this._settings.get_boolean('keyboard-haptics-enabled')))
            return;

        this._proxy.call(
            'Vibrate',
            null,
            Gio.DBusCallFlags.NONE,
            500,
            null,
            (proxy, result) => {
                try { proxy.call_finish(result); } catch (_) { /* No feedback when unavailable. */ }
            }
        );
    }
}
