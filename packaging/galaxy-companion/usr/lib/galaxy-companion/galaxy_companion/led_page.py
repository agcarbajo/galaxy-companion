# SPDX-License-Identifier: MIT
"""The status LED page: rules for when it lights up, in which colour and how."""
import json
import math

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from . import led_rules
from .i18n import _

BUS_NAME = "io.github.agcarbajo.GalaxyCompanion.Hardware"
OBJECT_PATH = "/io/github/agcarbajo/GalaxyCompanion/Hardware"

_css_loaded = False


def _load_css():
    """One class per palette colour, for the round swatch buttons."""
    global _css_loaded
    if _css_loaded or Gdk.Display.get_default() is None:
        return
    css = "".join(
        f".led-swatch-{color[1:]} {{ background: {color}; min-width: 32px; min-height: 32px; padding: 0;"
        f" border-radius: 9999px; box-shadow: inset 0 0 0 1px alpha(black, 0.15); }}\n"
        for color, _name in led_rules.PALETTE)
    css += ".led-swatch-selected { box-shadow: inset 0 0 0 1px alpha(black, 0.15), 0 0 0 2px @accent_bg_color; }\n"
    css += ".led-swatch-selected image { color: white; -gtk-icon-shadow: 0 1px 2px alpha(black, 0.5); }\n"
    provider = Gtk.CssProvider()
    provider.load_from_string(css) if hasattr(provider, "load_from_string") else provider.load_from_data(css.encode())
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                              Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _css_loaded = True


def color_dot(color, size=20):
    """A small lit-LED dot: the colour with a soft glow."""
    area = Gtk.DrawingArea(content_width=size, content_height=size, valign=Gtk.Align.CENTER)
    red, green, blue = (value / 255 for value in led_rules.rgb(color))

    def draw(_area, cr, width, height):
        cx, cy, radius = width / 2, height / 2, min(width, height) / 2
        cr.set_source_rgba(red, green, blue, 0.25)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgb(red, green, blue)
        cr.arc(cx, cy, radius * 0.62, 0, 2 * math.pi)
        cr.fill_preserve()
        cr.set_source_rgba(0, 0, 0, 0.18)
        cr.set_line_width(1)
        cr.stroke()
    area.set_draw_func(draw)
    return area


def installed_apps():
    """(desktop id without .desktop, name) for every app shown in the menus."""
    apps = {}
    for info in Gio.AppInfo.get_all():
        if info.should_show() and info.get_id():
            apps[info.get_id().removesuffix(".desktop")] = info.get_display_name()
    return sorted(apps.items(), key=lambda item: item[1].casefold())


class RuleDialog(Adw.Dialog):
    def __init__(self, page, rule, new=False):
        super().__init__(title=_("New rule") if new else _("Rule"), content_width=440, content_height=640)
        self.page = page
        self.rule = rule
        _load_css()

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        content = Adw.PreferencesPage()
        toolbar.set_content(content)
        self.set_child(toolbar)

        when = Adw.PreferencesGroup(title=_("When"))
        self.condition = Adw.ComboRow(title=_("Situation"), model=Gtk.StringList.new(
            [_(label) for _key, label in led_rules.CONDITIONS]))
        keys = [key for key, _label in led_rules.CONDITIONS]
        self.condition.set_selected(keys.index(rule["condition"]))
        self.condition.connect("notify::selected", self._condition_changed)
        when.add(self.condition)

        self.apps = [("", _("Any app"))] + installed_apps()
        if rule["app"] and rule["app"] not in dict(self.apps):
            self.apps.append((rule["app"], rule["app_name"] or rule["app"]))
        self.app = Adw.ComboRow(title=_("App"), model=Gtk.StringList.new([name for _id, name in self.apps]),
                                enable_search=True)
        self.app.set_selected(next(i for i, (app_id, _name) in enumerate(self.apps) if app_id == rule["app"]))
        self.app.connect("notify::selected", self._app_changed)
        when.add(self.app)

        self.threshold = Adw.SpinRow(title=_("Below"), subtitle=_("Battery level, in percent"),
                                     adjustment=Gtk.Adjustment(lower=5, upper=95, step_increment=5,
                                                               value=rule["threshold"]))
        self.threshold.connect("notify::value", self._threshold_changed)
        when.add(self.threshold)
        content.add(when)

        how = Adw.PreferencesGroup(title=_("How"))
        swatches = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                               max_children_per_line=10, min_children_per_line=5,
                               column_spacing=6, row_spacing=6, margin_top=12, margin_bottom=12,
                               margin_start=12, margin_end=12)
        self.swatch_buttons = {}
        for color, name in led_rules.PALETTE:
            button = Gtk.Button(css_classes=[f"led-swatch-{color[1:]}"], tooltip_text=_(name),
                                halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            button.update_property([Gtk.AccessibleProperty.LABEL], [_(name)])
            button.connect("clicked", lambda _b, c=color: self._set_color(c))
            self.swatch_buttons[color] = button
            swatches.append(button)
        self.custom = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False),
                                            tooltip_text=_("Custom colour"), valign=Gtk.Align.CENTER)
        self.custom.connect("notify::rgba", self._custom_color)
        self.color_row = Adw.ActionRow(title=_("Colour"))
        self.color_row.add_suffix(self.custom)
        how.add(self.color_row)
        # A preferences row, so the swatches sit inside the card under "Colour".
        how.add(Adw.PreferencesRow(activatable=False, child=swatches))

        self.effect = Adw.ComboRow(title=_("Effect"), model=Gtk.StringList.new(
            [_(label) for _key, label in led_rules.EFFECTS]))
        self.effect.set_selected([key for key, _label in led_rules.EFFECTS].index(rule["effect"]))
        self.effect.connect("notify::selected", self._effect_changed)
        how.add(self.effect)

        test = Adw.ActionRow(title=_("Try it on the LED"), subtitle=_("Shows this rule for five seconds"))
        test_button = Gtk.Button(label=_("Try"), valign=Gtk.Align.CENTER)
        test_button.connect("clicked", lambda _b: page.preview(self.rule))
        test.add_suffix(test_button)
        how.add(test)
        content.add(how)

        order = Adw.PreferencesGroup(title=_("Priority"), description=_(
            "When several rules hold at once, the one higher in the list wins."))
        box = Gtk.Box(spacing=12, homogeneous=True)
        self.up = Gtk.Button(label=_("Move Up"), css_classes=["pill"])
        self.up.connect("clicked", lambda _b: self._move(-1))
        self.down = Gtk.Button(label=_("Move Down"), css_classes=["pill"])
        self.down.connect("clicked", lambda _b: self._move(1))
        box.append(self.up)
        box.append(self.down)
        order.add(box)
        delete = Gtk.Button(label=_("Delete Rule"), css_classes=["pill", "destructive-action"],
                            halign=Gtk.Align.CENTER, margin_top=24)
        delete.connect("clicked", self._delete)
        order.add(delete)
        content.add(order)

        self._sync()

    def _sync(self):
        condition = self.rule["condition"]
        self.app.set_visible(condition == "notification")
        self.threshold.set_visible(condition == "battery-low")
        for color, button in self.swatch_buttons.items():
            selected = color == self.rule["color"]
            if selected:
                button.set_icon_name("object-select-symbolic")
                button.add_css_class("led-swatch-selected")
            else:
                button.set_child(None)
                button.remove_css_class("led-swatch-selected")
        self.color_row.set_subtitle(led_rules.color_name(self.rule["color"]))
        rgba = Gdk.RGBA()
        rgba.parse(self.rule["color"])
        if not self.custom.get_rgba().equal(rgba):
            self._syncing = True
            self.custom.set_rgba(rgba)
            self._syncing = False
        index = self.page.index_of(self.rule)
        self.up.set_sensitive(index > 0)
        self.down.set_sensitive(0 <= index < len(self.page.rules) - 1)

    def _changed(self):
        self.page.rule_changed(self.rule)
        self._sync()

    def _condition_changed(self, row, _pspec):
        self.rule["condition"] = led_rules.CONDITIONS[row.get_selected()][0]
        self._changed()

    def _app_changed(self, row, _pspec):
        app_id, name = self.apps[row.get_selected()]
        self.rule["app"], self.rule["app_name"] = app_id, name if app_id else ""
        self._changed()

    def _threshold_changed(self, row, _pspec):
        self.rule["threshold"] = int(row.get_value())
        self._changed()

    def _set_color(self, color):
        self.rule["color"] = color
        self._changed()

    def _custom_color(self, button, _pspec):
        if getattr(self, "_syncing", False):
            return
        rgba = button.get_rgba()
        self._set_color("#{:02x}{:02x}{:02x}".format(*(round(c * 255) for c in (rgba.red, rgba.green, rgba.blue))))

    def _effect_changed(self, row, _pspec):
        self.rule["effect"] = led_rules.EFFECTS[row.get_selected()][0]
        self._changed()

    def _move(self, step):
        self.page.move(self.rule, step)
        self._sync()

    def _delete(self, _button):
        self.page.delete(self.rule)
        self.close()


class LedPage(Adw.PreferencesPage):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.settings = window.settings
        self.set_margin_top(18)
        self.set_margin_bottom(18)

        general = Adw.PreferencesGroup(description=_(
            "The status LED lights up following the rules below. With it off, the LED "
            "goes back to what the system does on its own."))
        enabled = Adw.SwitchRow(title=_("Use the status LED"))
        self.settings.bind("led-enabled", enabled, "active", Gio.SettingsBindFlags.DEFAULT)
        general.add(enabled)
        brightness = Adw.ActionRow(title=_("Brightness"))
        scale = Gtk.Scale(adjustment=Gtk.Adjustment(lower=10, upper=100, step_increment=10, page_increment=10),
                          hexpand=True, valign=Gtk.Align.CENTER, width_request=160, draw_value=False)
        scale.set_value(self.settings.get_int("led-brightness"))
        scale.connect("value-changed", lambda s: self.settings.set_int("led-brightness", int(s.get_value())))
        brightness.add_suffix(scale)
        general.add(brightness)
        self.add(general)

        self.rules_group = Adw.PreferencesGroup(title=_("Rules"), description=_(
            "The first rule that holds, from the top, decides the colour."))
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=_("Add Rule"),
                         valign=Gtk.Align.CENTER, css_classes=["flat"])
        add.connect("clicked", self._add)
        self.rules_group.set_header_suffix(add)
        self.add(self.rules_group)
        self.rule_rows = []

        quiet = Adw.PreferencesGroup(title=_("Quiet Hours"))
        self.quiet = Adw.ExpanderRow(title=_("Turn the LED off at night"), show_enable_switch=True)
        self.settings.bind("led-quiet-enabled", self.quiet, "enable-expansion", Gio.SettingsBindFlags.DEFAULT)
        for key, title in (("led-quiet-start", _("From")), ("led-quiet-end", _("Until"))):
            row = Adw.SpinRow(title=title, adjustment=Gtk.Adjustment(lower=0, upper=23, step_increment=1))
            row.set_value(self.settings.get_int(key))
            row.connect("output", self._hour_output)
            row.connect("notify::value", lambda r, _p, k=key: (self.settings.set_int(k, int(r.get_value())),
                                                              self._quiet_subtitle()))
            self.quiet.add_row(row)
        self._quiet_subtitle()
        quiet.add(self.quiet)
        self.add(quiet)

        reset_group = Adw.PreferencesGroup()
        reset = Adw.ButtonRow(title=_("Restore Default Rules")) if hasattr(Adw, "ButtonRow") else None
        if reset is None:
            reset = Adw.ActionRow(title=_("Restore Default Rules"), activatable=True)
            reset.add_suffix(Gtk.Image(icon_name="edit-undo-symbolic"))
        reset.connect("activated", self._reset)
        reset_group.add(reset)
        self.add(reset_group)

        # With the LED off, everything that only shapes what it shows is moot.
        for widget in (brightness, self.rules_group, quiet, reset_group):
            self.settings.bind("led-enabled", widget, "sensitive", Gio.SettingsBindFlags.GET)

        self.settings.connect("changed::led-rules", lambda *_: self._reload())
        self._reload()

    # -- rules ----------------------------------------------------------------

    def _reload(self):
        self.rules = led_rules.load(self.settings.get_string("led-rules"))
        for row in self.rule_rows:
            self.rules_group.remove(row)
        self.rule_rows = []
        for rule in self.rules:
            row = Adw.ActionRow(title=led_rules.title(rule), subtitle=led_rules.subtitle(rule), activatable=True)
            row.add_prefix(color_dot(rule["color"]))
            # Prefixes stack towards the edge: added last, the handle sits leftmost.
            row.add_prefix(Gtk.Image(icon_name="list-drag-handle-symbolic", css_classes=["dim-label"],
                                     tooltip_text=_("Drag to change the priority")))
            self._make_draggable(row, rule)
            switch = Gtk.Switch(active=rule["enabled"], valign=Gtk.Align.CENTER)
            switch.connect("notify::active", lambda s, _p, r=rule: self._toggle(r, s.get_active()))
            row.add_suffix(switch)
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            row.connect("activated", lambda _row, r=rule: self._edit(r))
            self.rules_group.add(row)
            self.rule_rows.append(row)
        if not self.rules:
            row = Adw.ActionRow(title=_("No rules"), subtitle=_("The LED stays off. Add a rule with +."))
            self.rules_group.add(row)
            self.rule_rows.append(row)

    def _make_draggable(self, row, rule):
        """Drag a rule by its row and drop it on another to take its place."""
        source = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        source.connect("prepare", lambda *_: Gdk.ContentProvider.new_for_value(rule["id"]))
        source.connect("drag-begin", lambda src, _drag: src.set_icon(Gtk.WidgetPaintable(widget=row), 24, 24))
        row.add_controller(source)
        target = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        target.connect("drop", lambda _t, value, _x, _y: self.move_to(value, self.index_of(rule)))
        row.add_controller(target)

    def move_to(self, rule_id, index):
        current = self.index_of({"id": rule_id})
        if current < 0 or index < 0 or current == index:
            return False
        self.rules.insert(index, self.rules.pop(current))
        self._save()
        return True

    def _save(self):
        self.settings.set_string("led-rules", led_rules.dump(self.rules))

    def index_of(self, rule):
        return next((i for i, item in enumerate(self.rules) if item["id"] == rule["id"]), -1)

    def rule_changed(self, rule):
        index = self.index_of(rule)
        if index >= 0:
            self.rules[index] = dict(rule)
            self._save()

    def _toggle(self, rule, active):
        if rule["enabled"] != active:
            rule["enabled"] = active
            self.rule_changed(rule)

    def move(self, rule, step):
        index = self.index_of(rule)
        target = index + step
        if index >= 0 and 0 <= target < len(self.rules):
            self.rules[index], self.rules[target] = self.rules[target], self.rules[index]
            self._save()

    def delete(self, rule):
        self.rules = [item for item in self.rules if item["id"] != rule["id"]]
        self._save()

    def _edit(self, rule, new=False):
        dialog = RuleDialog(self, dict(rule), new=new)
        dialog.present(self.window)
        return dialog

    def _add(self, _button):
        rule = led_rules.new_rule("notification", color="#9141ac", effect="breathe")
        self.rules.insert(0, rule)
        self._save()
        self._edit(rule, new=True)

    def _reset(self, _row):
        self.settings.reset("led-rules")

    def preview(self, rule):
        try:
            Gio.bus_get_sync(Gio.BusType.SESSION, None).call(
                BUS_NAME, OBJECT_PATH, BUS_NAME, "PreviewLed", GLib.Variant("(s)", (json.dumps(rule),)),
                None, Gio.DBusCallFlags.NONE, 5000, None, None)
        except GLib.Error:
            pass

    # -- quiet hours ----------------------------------------------------------

    @staticmethod
    def _hour_output(row):
        row.set_text(f"{int(row.get_value()):02d}:00")
        return True

    def _quiet_subtitle(self):
        self.quiet.set_subtitle(_("From {start} to {end}").format(
            start=f"{self.settings.get_int('led-quiet-start'):02d}:00",
            end=f"{self.settings.get_int('led-quiet-end'):02d}:00"))
