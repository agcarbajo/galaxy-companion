#!/usr/bin/env python3
"""Extensions come back after a crash, a crash loop stops, a person's choice stands."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packaging/galaxy-companion"
sys.path.insert(0, str(PACKAGE / "usr/lib/galaxy-companion"))
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from galaxy_companion import shell_extensions as x


class Store:
    def __init__(self, off=False, disabled=()):
        self.values = {x.OFF_KEY: off, x.DISABLED_KEY: list(disabled)}

    def get_boolean(self, key):
        return self.values[key]

    def set_boolean(self, key, value):
        self.values[key] = value

    def get_strv(self, key):
        return list(self.values[key])

    def set_strv(self, key, value):
        self.values[key] = list(value)


class FakeShell:
    """Applies GNOME's rule: session-mode extensions ignore the global switch, not the disabled list."""

    def __init__(self, store, user=(), mode=(), broken=()):
        self.store, self.user, self.mode, self.broken = store, set(user), set(mode), set(broken)
        self.cycles = {uuid: 0 for uuid in self.user | self.mode}
        self.running = set()

    def __call__(self):
        wanted = set(self.mode)
        if not self.store.get_boolean(x.OFF_KEY):
            wanted |= self.user
        wanted -= set(self.store.get_strv(x.DISABLED_KEY))
        for uuid in wanted - self.running:
            self.cycles[uuid] += 1
        self.running = set(wanted)
        return {uuid: {"enabled": uuid in wanted,
                       "state": x.ERROR if uuid in self.broken and uuid in wanted
                       else x.ACTIVE if uuid in wanted else x.INACTIVE}
                for uuid in self.user | self.mode}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        state = Path(self.tmp.name) / "state/shell-extensions.json"
        for patcher in (patch.object(x, "STATE", state),
                        patch.object(x.Gio.Settings, "sync", lambda *_a: None)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.notified = []
        self.pauses = []

    def recover(self, store):
        return x.recover(store, pause=self.pauses.append, notify=lambda: self.notified.append(1))

    def crash(self, store):
        """One flagged crash: the record, then what GNOME's unit does."""
        x.record_crash(store)
        store.set_boolean(x.OFF_KEY, True)


class CrashRecovery(Base):
    def test_a_normal_session_does_nothing(self):
        store = Store()
        self.assertEqual(self.recover(store), "idle")
        self.assertFalse(x.STATE.exists())
        self.assertEqual(self.pauses, [])

    def test_one_crash_is_undone_and_forgotten(self):
        store = Store()
        self.crash(store)
        self.assertEqual(self.recover(store), "restored")
        self.assertFalse(store.get_boolean(x.OFF_KEY))
        self.assertEqual(self.pauses, [x.HEALTHY_SECONDS])
        self.assertFalse(x.STATE.exists())

    def test_the_healthy_wait_outlasts_gnomes_blame_window(self):
        self.assertGreater(x.HEALTHY_SECONDS, 60)

    def test_a_switch_the_person_turned_off_is_left_alone(self):
        store = Store(off=True)
        self.assertEqual(self.recover(store), "idle")
        self.assertTrue(store.get_boolean(x.OFF_KEY))
        self.assertFalse(x.record_crash(store))
        self.assertFalse(x.STATE.exists())

    def test_crash_loop_stops_and_says_so(self):
        store = Store()
        def killed(_seconds):
            raise SystemExit
        for attempt in range(1, x.MAX_ATTEMPTS):
            self.crash(store)
            # Each retry dies during its healthy wait, so the count stands.
            with self.assertRaises(SystemExit):
                x.recover(store, pause=killed)
            self.assertFalse(store.get_boolean(x.OFF_KEY))
            self.assertEqual(json.loads(x.STATE.read_text())["attempts"], attempt)
        self.crash(store)
        self.assertEqual(self.recover(store), "held")
        self.assertTrue(store.get_boolean(x.OFF_KEY))
        self.assertEqual(self.notified, [1])
        self.assertEqual(self.recover(store), "held")   # Stays off at the next login too.
        self.assertTrue(store.get_boolean(x.OFF_KEY))

    def test_a_session_killed_in_its_wait_keeps_the_count(self):
        store = Store()
        self.crash(store)
        def killed(_seconds):
            raise SystemExit
        with self.assertRaises(SystemExit):
            x.recover(store, pause=killed)
        self.assertEqual(json.loads(x.STATE.read_text())["attempts"], 1)

    def test_turning_them_on_by_hand_ends_a_hold(self):
        store = Store()
        x._write({"attempts": x.MAX_ATTEMPTS, "held": True})
        store.set_boolean(x.OFF_KEY, False)
        self.assertEqual(self.recover(store), "restored")
        self.assertFalse(x.STATE.exists())

    def test_a_damaged_state_file_is_not_fatal(self):
        x.STATE.parent.mkdir(parents=True)
        x.STATE.write_text("{not json")
        self.assertEqual(self.recover(Store()), "idle")


class Restart(Base):
    def run_restart(self, shell, store):
        return x.restart(store, listing=shell, pause=lambda _s: shell())

    def test_every_kind_of_extension_is_reloaded(self):
        store = Store(disabled=["mine-off@x"])
        shell = FakeShell(store, user=["a@x", "b@x", "mine-off@x"], mode=["dock@x"])
        shell()
        before = dict(shell.cycles)
        result = self.run_restart(shell, store)
        self.assertEqual(result, {"restarted": ["a@x", "b@x", "dock@x"], "failed": []})
        for uuid in ("a@x", "b@x", "dock@x"):
            self.assertEqual(shell.cycles[uuid], before[uuid] + 1, uuid)
        self.assertEqual(shell.cycles["mine-off@x"], 0)

    def test_the_personal_disabled_list_is_preserved(self):
        store = Store(disabled=["mine-off@x"])
        self.run_restart(FakeShell(store, user=["a@x", "mine-off@x"]), store)
        self.assertEqual(store.get_strv(x.DISABLED_KEY), ["mine-off@x"])
        self.assertFalse(x.STATE.exists())

    def test_it_clears_the_global_switch_and_a_hold(self):
        store = Store(off=True)
        x._write({"attempts": x.MAX_ATTEMPTS, "held": True})
        shell = FakeShell(store, user=["a@x"], mode=["dock@x"])
        result = self.run_restart(shell, store)
        self.assertFalse(store.get_boolean(x.OFF_KEY))
        self.assertEqual(result["restarted"], ["a@x", "dock@x"])
        self.assertFalse(x.STATE.exists())

    def test_an_extension_in_error_is_reported(self):
        store = Store()
        result = self.run_restart(FakeShell(store, user=["a@x", "bad@x"], broken=["bad@x"]), store)
        self.assertEqual(result, {"restarted": ["a@x"], "failed": ["bad@x"]})

    def test_shell_vanishing_midway_restores_the_list(self):
        store = Store(disabled=["mine-off@x"])
        shell = FakeShell(store, user=["a@x"])
        calls = []
        def dying():
            calls.append(1)
            if len(calls) > 1:
                raise x.GLib.Error("Shell is gone")
            return shell()
        with self.assertRaises(x.GLib.Error):
            x.restart(store, listing=dying, pause=lambda _s: None)
        self.assertEqual(store.get_strv(x.DISABLED_KEY), ["mine-off@x"])
        self.assertFalse(x.STATE.exists())

    def test_a_restart_killed_midway_is_finished_by_the_next_session(self):
        store = Store(disabled=["a@x", "b@x", "mine-off@x"])
        x._write({"restart_disabled": ["mine-off@x"]})
        self.assertEqual(self.recover(store), "restored")
        self.assertEqual(store.get_strv(x.DISABLED_KEY), ["mine-off@x"])
        self.assertFalse(x.STATE.exists())


class Packaging(unittest.TestCase):
    units = PACKAGE / "usr/lib/systemd/user"

    def test_crash_record_runs_before_gnome_sets_the_switch(self):
        text = (self.units / "org.gnome.Shell-disable-extensions.service.d/90-galaxy-companion.conf").read_text()
        self.assertIn("ExecStartPre=-/usr/libexec/galaxy-companion-shell-extensions record-crash", text)

    def test_unit_only_runs_when_there_is_something_to_do(self):
        text = (self.units / "galaxy-companion-extension-recovery.service").read_text()
        self.assertIn("ConditionPathExists=%h/.local/state/galaxy-companion/shell-extensions.json", text)
        self.assertEqual(x.STATE, Path.home() / ".local/state/galaxy-companion/shell-extensions.json")
        self.assertIn("WantedBy=graphical-session.target", text)

    def test_enabled_on_install_and_disabled_on_removal(self):
        name = "--global enable galaxy-companion-extension-recovery.service"
        self.assertIn(name, (PACKAGE / "DEBIAN/postinst").read_text())
        self.assertIn(name.replace("enable", "disable", 1), (PACKAGE / "DEBIAN/postrm").read_text())

    def test_nothing_is_tied_to_one_device(self):
        for path in (PACKAGE / "usr/lib/galaxy-companion/galaxy_companion/shell_extensions.py",
                     PACKAGE / "usr/lib/galaxy-companion/galaxy_companion/shell_extensions_ui.py",
                     PACKAGE / "usr/libexec/galaxy-companion-shell-extensions"):
            text = path.read_text(encoding="utf-8").lower()
            for word in ("gts9", "sm-x9", "tab s9", "@agcarbajo", "device.current"):
                self.assertNotIn(word, text, path.name)


class Interface(unittest.TestCase):
    def test_the_row_appears_in_troubleshooting_on_any_device(self):
        from gi.repository import Adw, Gtk
        if not Gtk.init_check():
            self.skipTest("no display")
        Adw.init()
        from galaxy_companion import shell_extensions_ui as ui
        about = Adw.AboutWindow(application_name="t", debug_info="x")
        with patch.object(ui.shell_extensions, "available", return_value=True):
            row = ui.add_to_about(about)
        self.assertIsNotNone(row)
        self.assertTrue(row.get_activatable())
        with patch.object(ui.shell_extensions, "available", return_value=False):
            self.assertIsNone(ui.add_to_about(about))

    def test_strings_are_translated(self):
        from galaxy_companion.i18n import TRANSLATIONS
        source = (PACKAGE / "usr/lib/galaxy-companion/galaxy_companion/shell_extensions_ui.py").read_text(encoding="utf-8") \
            + (PACKAGE / "usr/lib/galaxy-companion/galaxy_companion/shell_extensions.py").read_text(encoding="utf-8")
        import re
        strings = re.findall(r'_\("((?:[^"\\]|\\.)*)"\)', source)
        self.assertGreaterEqual(len(strings), 9)
        for text in strings:
            self.assertEqual(len(TRANSLATIONS.get(text, ())), 5, text)


if __name__ == "__main__":
    unittest.main()
