#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Status LED rules and engine, and the battery charge limit, against fake sysfs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packaging/galaxy-companion/usr/lib/galaxy-companion"
LED_HELPER = ROOT / "packaging/galaxy-companion/usr/libexec/galaxy-companion-led"
os.environ["GALAXY_COMPANION_DEVICE"] = "star2lte"
sys.path.insert(0, str(PACKAGE))
from galaxy_companion import charge_limit, device, led_engine, led_rules  # noqa: E402


def status(**values):
    base = {"battery": 50, "battery_status": "Discharging", "plugged": False, "notifications": [], "media": False}
    base.update(values)
    return base


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.rules = led_rules.defaults()

    def test_defaults_follow_priority(self):
        choose = lambda **v: (led_rules.choose(self.rules, status(**v)) or {}).get("condition")
        self.assertIsNone(choose())
        self.assertEqual(choose(battery_status="Charging"), "charging")
        self.assertEqual(choose(battery_status="Full", plugged=True, battery=100), "charged")
        self.assertEqual(choose(battery=10), "battery")
        # A waiting notification outranks everything below it.
        self.assertEqual(choose(battery=10, notifications=[{"org.telegram.desktop"}]), "notification")
        # Charging is not "low", even at 10 %.
        self.assertEqual(choose(battery=10, battery_status="Charging"), "charging")

    def test_battery_ranges_and_charger(self):
        def holds(rule, **values):
            return led_rules.matches(led_rules.clean(dict(rule, condition="battery")), status(**values))
        middle = {"battery_min": 50, "battery_max": 80}
        self.assertTrue(holds(middle, battery=50))
        self.assertTrue(holds(middle, battery=80), "both ends count")
        self.assertFalse(holds(middle, battery=81))
        self.assertTrue(holds(middle, battery=60, battery_status="Charging"), "the charger does not matter")
        self.assertTrue(holds({"battery_min": 0, "battery_max": 100}, battery=0))
        self.assertFalse(holds({"battery_min": 0, "battery_max": 100}, battery=None))
        plugged = dict(middle, power="plugged")
        self.assertFalse(holds(plugged, battery=60))
        self.assertTrue(holds(plugged, battery=60, plugged=True))
        self.assertTrue(holds(plugged, battery=60, battery_status="Charging"))
        unplugged = dict(middle, power="unplugged")
        self.assertTrue(holds(unplugged, battery=60))
        self.assertFalse(holds(unplugged, battery=60, battery_status="Charging"))

    def test_battery_ranges_are_cleaned(self):
        rule = led_rules.clean({"condition": "battery", "battery_min": 90, "battery_max": 20, "power": "x"})
        self.assertEqual((rule["battery_min"], rule["battery_max"], rule["power"]), (20, 90, "any"))
        rule = led_rules.clean({"condition": "battery", "battery_min": -5, "battery_max": 500})
        self.assertEqual((rule["battery_min"], rule["battery_max"]), (0, 100))

    def test_old_low_battery_rules_become_ranges(self):
        rule = led_rules.clean({"condition": "battery-low", "threshold": 20, "color": "#e01b24"})
        self.assertEqual((rule["condition"], rule["battery_min"], rule["battery_max"], rule["power"]),
                         ("battery", 0, 20, "unplugged"))
        self.assertNotIn("threshold", rule)

    def test_app_rules_match_desktop_id_or_name(self):
        rule = led_rules.new_rule("notification", app="org.telegram.desktop", app_name="Telegram")
        self.assertTrue(led_rules.matches(rule, status(notifications=[{"org.telegram.desktop"}])))
        self.assertTrue(led_rules.matches(rule, status(notifications=[{"telegram"}])))
        self.assertFalse(led_rules.matches(rule, status(notifications=[{"thunderbird"}])))

    def test_disabled_rules_never_match(self):
        rule = led_rules.new_rule("charging", enabled=False)
        self.assertFalse(led_rules.matches(rule, status(battery_status="Charging")))

    def test_bad_stored_rules_are_cleaned_or_dropped(self):
        stored = json.dumps([{"condition": "charging", "color": "red", "effect": "disco", "battery_max": 500},
                             {"condition": "rm -rf"}, "junk"])
        rules = led_rules.load(stored)
        self.assertEqual(len(rules), 1)
        self.assertEqual((rules[0]["color"], rules[0]["effect"], rules[0]["battery_max"]),
                         ("#3584e4", "breathe", 100))
        self.assertEqual(len(led_rules.load("")), 4)

    def test_quiet_hours_cross_midnight(self):
        self.assertTrue(led_rules.in_quiet_hours(23, 23, 7))
        self.assertTrue(led_rules.in_quiet_hours(3, 23, 7))
        self.assertFalse(led_rules.in_quiet_hours(7, 23, 7))
        self.assertFalse(led_rules.in_quiet_hours(12, 23, 7))
        self.assertTrue(led_rules.in_quiet_hours(14, 13, 15))
        self.assertFalse(led_rules.in_quiet_hours(5, 5, 5))

    def test_titles(self):
        battery = led_rules.new_rule("battery", battery_min=50, battery_max=80, power="plugged",
                                     color="#33d17a", effect="solid")
        self.assertEqual(led_rules.title(battery), "Battery between 50 and 80 %")
        self.assertEqual(led_rules.subtitle(battery), "Steady · Green · Plugged in")
        self.assertEqual(led_rules.title(led_rules.new_rule("notification", app="x", app_name="Signal")),
                         "Notification from Signal")
        self.assertEqual(led_rules.subtitle(led_rules.new_rule("charging", color="#ff7800", effect="solid")),
                         "Steady · Orange")


class CustomConditionTests(unittest.TestCase):
    def test_signal_and_command_rules(self):
        signal = led_rules.clean({"condition": "signal", "signal": "backup"})
        self.assertTrue(led_rules.matches(signal, status(signals={"backup"})))
        self.assertFalse(led_rules.matches(signal, status(signals={"other"})))
        command = led_rules.clean({"condition": "command", "command": "true", "interval": 5})
        self.assertEqual(command["interval"], 30, "never more often than every 30 s")
        self.assertTrue(led_rules.matches(command, status(commands={"true": True})))
        self.assertFalse(led_rules.matches(command, status(commands={"true": False})))
        self.assertFalse(led_rules.matches(command, status()), "not run yet")

    def test_bad_signal_names_are_dropped(self):
        for name in ("../x", "a b", "x" * 65, "ñ"):
            self.assertEqual(led_rules.clean({"condition": "signal", "signal": name})["signal"], "")

    def test_advanced_rules_only_count_when_allowed(self):
        rules = [led_rules.clean({"condition": "signal", "signal": "s"}), led_rules.new_rule("charging")]
        self.assertEqual([r["condition"] for r in led_rules.usable(rules, False)], ["charging"])
        self.assertEqual(len(led_rules.usable(rules, True)), 2)


class FakeSettings:
    def __init__(self, **values):
        self.values = {"led-enabled": True, "led-rules": "", "led-brightness": 60, "led-advanced": False,
                       "led-quiet-enabled": False, "led-quiet-start": 23, "led-quiet-end": 7}
        self.values.update(values)

    def connect(self, *_args):
        return 0

    get_boolean = get_string = get_int = lambda self, key: self.values[key]


def power(directory, capacity, state, online):
    root = Path(directory)
    for name, files in (("max170xx_battery", {"type": "Battery", "present": "1", "capacity": capacity,
                                              "status": state}),
                        ("max77705-charger", {"type": "USB", "online": online})):
        (root / name).mkdir(exist_ok=True)
        for key, value in files.items():
            (root / name / key).write_text(f"{value}\n")
    return root


class EngineTests(unittest.TestCase):
    def engine(self, **settings):
        calls = []
        with patch.object(led_engine.Gio, "bus_get_sync", side_effect=led_engine.GLib.Error("no bus")):
            engine = led_engine.LedEngine(FakeSettings(**settings),
                                          run=lambda wanted, done: (calls.append(wanted), done(wanted, True)))
        self.addCleanup(engine.close if False else (lambda: led_engine.GLib.source_remove(engine.timer)))
        return engine, calls

    def test_engine_shows_charging_then_notification_and_writes_only_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(led_engine, "POWER_SUPPLY", power(directory, 40, "Charging", 1)):
                engine, calls = self.engine()
                self.assertEqual(calls[-1], ("show", "solid", "#ff7800", "60"))
                engine.evaluate()
                self.assertEqual(len(calls), 1, "unchanged state is not rewritten")
                engine.notification({"org.gnome.evolution"})
                self.assertEqual(calls[-1], ("show", "breathe", "#3584e4", "60"))

    def test_disabled_gives_the_led_back_and_quiet_hours_turn_it_off(self):
        engine, calls = self.engine(**{"led-enabled": False})
        self.assertEqual(calls[-1], ("restore",))
        hour = time.localtime().tm_hour
        engine, calls = self.engine(**{"led-quiet-enabled": True, "led-quiet-start": hour,
                                       "led-quiet-end": (hour + 1) % 24})
        self.assertEqual(calls[-1], ("off",))

    def test_preview_overrides_for_a_while(self):
        engine, calls = self.engine()
        engine.show_preview(led_rules.new_rule("media", color="#9141ac", effect="blink-fast"))
        self.assertEqual(calls[-1], ("show", "blink-fast", "#9141ac", "60"))
        engine.show_preview(None)
        self.assertEqual(calls[-1], ("off",), "closing the rule ends the try at once")
        self.assertIsNone(engine.preview_timer)

    def test_a_helper_that_never_answers_does_not_block_the_led(self):
        engine, _calls = self.engine()
        # sleep stands in for a helper stuck in the kernel by a broken driver.
        engine.argv = lambda wanted: ["sleep", "30"]
        answers = []
        with patch.object(led_engine, "HELPER_TIMEOUT", 1):
            engine._spawn(("off",), lambda wanted, ok: answers.append((wanted, ok)))
            context = led_engine.GLib.MainContext.default()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not answers:
                context.iteration(False)
                time.sleep(0.01)
        self.assertEqual(answers, [(("off",), False)])

    def test_signals_need_the_advanced_switch(self):
        rules = json.dumps([led_rules.clean({"condition": "signal", "signal": "backup", "color": "#33d17a",
                                             "effect": "solid"})])
        engine, calls = self.engine(**{"led-rules": rules})
        self.assertTrue(engine.set_signal("backup", True))
        self.assertEqual(calls[-1], ("off",), "ignored while custom conditions are off")
        engine, calls = self.engine(**{"led-rules": rules, "led-advanced": True})
        engine.set_signal("backup", True)
        self.assertEqual(calls[-1], ("show", "solid", "#33d17a", "60"))
        engine.set_signal("backup", False)
        self.assertEqual(calls[-1], ("off",))
        self.assertFalse(engine.set_signal("../etc", True))

    def test_commands_run_and_their_result_lights_the_led(self):
        rules = json.dumps([led_rules.clean({"condition": "command", "command": cmd, "color": color,
                                             "effect": "solid"})
                            for cmd, color in (("exit 1", "#e01b24"), ("sleep 30", "#f6d32d"),
                                               ("true", "#3584e4"))])
        with patch.object(led_rules, "COMMAND_TIMEOUT", 1):
            engine, calls = self.engine(**{"led-rules": rules, "led-advanced": True})
            context = led_engine.GLib.MainContext.default()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and len(engine.command_results) < 3:
                context.iteration(False)
                time.sleep(0.01)
        self.assertEqual(engine.command_results, {"exit 1": False, "sleep 30": False, "true": True})
        self.assertEqual(calls[-1], ("show", "solid", "#3584e4", "60"))

    def test_notification_sources(self):
        sources = led_engine.notification_sources(
            "org.freedesktop.Notifications",
            ["Telegram Desktop", 0, "", "Hi", "", [], {"desktop-entry": "org.telegram.desktop"}, -1])
        self.assertEqual(sources, {"telegram desktop", "org.telegram.desktop"})
        self.assertEqual(led_engine.notification_sources("org.gtk.Notifications", ["org.gnome.Calendar"]),
                         {"org.gnome.calendar"})


class ChargeLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "max77705-charger").mkdir()
        (self.root / "max170xx_battery").mkdir()
        self.behaviour = self.root / "max77705-charger" / "charge_behaviour"
        self.behaviour.write_text("[auto] inhibit-charge\n")

    def at(self, level, enabled=True, limit=80):
        (self.root / "max170xx_battery" / "capacity").write_text(f"{level}\n")
        charge_limit.apply({"enabled": enabled, "limit": limit}, root=self.root)
        value = self.behaviour.read_text().strip()
        # Emulate the kernel: the written value becomes the bracketed one.
        if "[" not in value:
            self.behaviour.write_text(" ".join(f"[{v}]" if v == value else v
                                               for v in ("auto", "inhibit-charge")) + "\n")
        return "inhibit" if "[inhibit-charge]" in self.behaviour.read_text() else "auto"

    def test_s9_plus_has_a_confirmed_limit_and_the_tab_has_none(self):
        self.assertTrue(charge_limit.available())
        with patch.dict(os.environ, {"GALAXY_COMPANION_DEVICE": "gts9uwifi"}):
            device.current(refresh=True)
            try:
                self.assertFalse(charge_limit.available())
            finally:
                os.environ["GALAXY_COMPANION_DEVICE"] = "star2lte"
                device.current(refresh=True)

    def test_stops_at_the_limit_and_resumes_below_the_window(self):
        self.assertEqual(self.at(70), "auto")
        self.assertEqual(self.at(80), "inhibit")
        self.assertEqual(self.at(78), "inhibit", "inside the window nothing changes")
        self.assertEqual(self.at(75), "auto")
        self.assertEqual(self.at(77), "auto")
        self.assertEqual(self.at(90, enabled=False), "auto")

    def test_release_resumes_charging(self):
        self.at(85)
        charge_limit.release(root=self.root)
        self.assertIn("auto", self.behaviour.read_text())

    def test_state_file_round_trip_and_validation(self):
        state = self.root / "state.json"
        self.assertEqual(charge_limit.load(state), {"enabled": False, "limit": 80})
        charge_limit.save(True, 85, state)
        self.assertEqual(charge_limit.load(state), {"enabled": True, "limit": 85})
        with self.assertRaises(ValueError):
            charge_limit.save(True, 42, state)

    def test_led_helper_refuses_on_a_device_without_led(self):
        result = subprocess.run([sys.executable, str(LED_HELPER), "show", "solid", "#ff0000", "50"],
                                capture_output=True, text=True,
                                env=dict(os.environ, GALAXY_COMPANION_DEVICE="gts9uwifi"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no status LED", result.stderr)


class BixbyButtonTests(unittest.TestCase):
    """The backend's gesture detector, driven with fake key presses."""

    def setUp(self):
        import importlib.machinery, importlib.util
        path = ROOT / "packaging/galaxy-companion/usr/libexec/galaxy-companion-hardware"
        loader = importlib.machinery.SourceFileLoader("hardware_backend", str(path))
        spec = importlib.util.spec_from_loader("hardware_backend", loader)
        self.backend = importlib.util.module_from_spec(spec)
        loader.exec_module(self.backend)

    def gestures(self, double="nothing"):
        done = []
        settings = FakeSettings(**{"bixby-single-press": "screenshot", "bixby-double-press": double,
                                   "bixby-long-press": "flashlight"})
        return self.backend.ButtonGestures("bixby", settings, done.append), done

    def spin(self, seconds):
        context = led_engine.GLib.MainContext.default()
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            context.iteration(False)
            time.sleep(0.005)

    def test_single_press_fires_at_once_when_double_press_does_nothing(self):
        button, done = self.gestures()
        button.press(); button.release()
        self.assertEqual(done, ["bixby-single-press"])

    def test_double_press_and_single_press_with_a_double_mapping(self):
        button, done = self.gestures(double="play-pause")
        button.press(); button.release(); button.press(); button.release()
        self.assertEqual(done, ["bixby-double-press"])
        button.press(); button.release()
        self.spin(0.45)
        self.assertEqual(done, ["bixby-double-press", "bixby-single-press"])

    def test_long_press_fires_once_and_not_a_single_press(self):
        button, done = self.gestures()
        button.press()
        self.spin(0.75)
        button.release()
        self.assertEqual(done, ["bixby-long-press"])

    def test_s9_plus_profile_maps_the_bixby_key(self):
        found = device.current(refresh=True)
        self.assertTrue(found.has("bixby-key"))
        self.assertEqual((found.bixby_key["input"], found.bixby_key["code"]), ("gpio-keys", 212))


class SignalCommandLineTests(unittest.TestCase):
    def test_bad_arguments_are_refused_before_any_bus_call(self):
        from galaxy_companion import main
        with patch.object(main.Gio, "bus_get_sync", side_effect=AssertionError("no bus call")):
            for args in ([], ["backup"], ["backup", "maybe"], ["bad name", "on"]):
                with patch("sys.stderr"):
                    self.assertEqual(main.led_signal(args), 2, args)


REORDER = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1])
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Adw
Adw.init()
from galaxy_companion import window
page = window.CompanionWindow(None).view_stack.get_child_by_name("led")
names = lambda: [r["condition"] for r in page.rules]
before = names()
page.move_to(page.rules[3]["id"], 0)   # drop "charged" on the first row
page.settings.set_boolean("led-enabled", False)
off = page.rules_group.get_sensitive()
page.settings.set_boolean("led-enabled", True)
print(json.dumps([before, names(), off, page.rules_group.get_sensitive()]))
"""


@unittest.skipUnless(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"), "needs a display")
class ReorderTests(unittest.TestCase):
    def test_dropping_a_rule_on_another_takes_its_place_and_is_saved(self):
        result = subprocess.run([sys.executable, "-c", REORDER, str(PACKAGE)], capture_output=True, text=True,
                                env=dict(os.environ, GALAXY_COMPANION_DEVICE="star2lte"), timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        before, after, off, on = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual((off, on), (False, True), "rules follow the LED switch")
        self.assertEqual(before, ["notification", "battery", "charging", "charged"])
        self.assertEqual(after, ["charged", "notification", "battery", "charging"])


DIALOG = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Adw
Adw.init()
from galaxy_companion import led_page, window
win = window.CompanionWindow(None)
page = win.view_stack.get_child_by_name("led")
previews = []
page.preview = previews.append
rule = next(r for r in page.rules if r["condition"] == "battery")
dialog = led_page.RuleDialog(page, dict(rule))
shown = [row.get_visible() for row in (dialog.battery_min, dialog.battery_max, dialog.power, dialog.app)]
dialog.battery_max.set_value(60)
dialog.battery_min.set_value(80)     # past the top: the top follows
dialog.power.set_selected(2)
saved = next(r for r in page.rules if r["id"] == rule["id"])
dialog._try(None)
dialog.emit("closed")
print(json.dumps([shown, [saved["battery_min"], saved["battery_max"], saved["power"]],
                  [p if p is None else p["id"] for p in previews]]))
"""


@unittest.skipUnless(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"), "needs a display")
class RuleDialogTests(unittest.TestCase):
    def test_battery_range_rows_and_closing_ends_the_try(self):
        result = subprocess.run([sys.executable, "-c", DIALOG, str(PACKAGE)], capture_output=True, text=True,
                                env=dict(os.environ, GALAXY_COMPANION_DEVICE="star2lte"), timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        shown, saved, previews = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(shown, [True, True, True, False], "range and charger rows, no app row")
        self.assertEqual(saved, [80, 80, "plugged"])
        self.assertEqual(len(previews), 2)
        self.assertIsNone(previews[1], "closing the dialog ends the try")


if __name__ == "__main__":
    unittest.main()
