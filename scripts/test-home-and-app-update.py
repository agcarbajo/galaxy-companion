#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Home page facts, Galaxy Companion's own updater, and the narrow-window menu."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packaging/galaxy-companion/usr/lib/galaxy-companion"
HELPER = ROOT / "packaging/galaxy-companion/usr/libexec/galaxy-companion-self-update"
sys.path.insert(0, str(PACKAGE))
from galaxy_companion import app_update, system_summary  # noqa: E402

DIGEST = "a" * 64


def release(*names, size=1000):
    return {"tag_name": "v2.2.0", "body": "Notes", "html_url": "https://github.com/x",
            "assets": [{"name": name, "size": size, "browser_download_url": f"https://example.invalid/{name}"}
                       for name in names]}


class MemoryTests(unittest.TestCase):
    def test_reported_memory_rounds_up_to_the_size_sold(self):
        gib = 1024**2
        self.assertEqual(system_summary.marketed_memory(int(15.2 * gib)), "16 GB")
        self.assertEqual(system_summary.marketed_memory(int(5.6 * gib)), "6 GB")
        self.assertEqual(system_summary.marketed_memory(int(11.1 * gib)), "12 GB")
        self.assertEqual(system_summary.marketed_memory(int(1.4 * gib)), "1.5 GB")
        self.assertEqual(system_summary.marketed_memory(0), "")

    def test_meminfo_is_read(self):
        with tempfile.NamedTemporaryFile("w", suffix="meminfo") as stream:
            stream.write("MemTotal:       15938244 kB\nMemFree: 1 kB\n")
            stream.flush()
            with patch.object(system_summary, "MEMINFO", stream.name):
                self.assertEqual(system_summary.marketed_memory(system_summary.memory_kib()), "16 GB")


class ReleaseTests(unittest.TestCase):
    def test_release_with_package_and_sums(self):
        info = app_update.parse_release(release("galaxy-companion_2.2.0_all.deb", "SHA256SUMS"),
                                        f"{DIGEST}  galaxy-companion_2.2.0_all.deb\n")
        self.assertEqual((info["version"], info["sha256"], info["size"]), ("2.2.0", DIGEST, 1000))

    def test_release_must_list_the_package_in_sums(self):
        with self.assertRaises(app_update.UpdateError):
            app_update.parse_release(release("galaxy-companion_2.2.0_all.deb"), f"{DIGEST}  other.deb\n")

    def test_release_without_exactly_one_package(self):
        for names in ((), ("galaxy-companion_2.2.0_all.deb", "galaxy-companion_2.1.9_all.deb"),
                      ("galaxy-companion_2.2.0_arm64.deb",), ("../galaxy-companion_2.2.0_all.deb",)):
            with self.assertRaises(app_update.UpdateError, msg=names):
                app_update.parse_release(release(*names), "")

    def test_oversized_package_is_refused(self):
        with self.assertRaises(app_update.UpdateError):
            app_update.parse_release(release("galaxy-companion_2.2.0_all.deb", size=app_update.MAX_DEB + 1),
                                     f"{DIGEST}  galaxy-companion_2.2.0_all.deb\n")

    def test_version_order(self):
        # The installed version is dpkg's, with the epoch of the current scheme.
        self.assertTrue(app_update.newer("2.10.0", "1:2.9.1"))
        self.assertFalse(app_update.newer("2.1.0", "1:2.1.0"))
        self.assertFalse(app_update.newer("2.0.9", "1:2.1.0"))

    def test_restarted_numbering_ranks_above_every_pre_restart_package(self):
        # Installed before the restart: Tab Companion 1.5.x, Galaxy Companion 2.x.
        for installed in ("1.5.8", "2.3.0", "2.5.1"):
            self.assertTrue(app_update.newer("0.9.0", installed), installed)
        # Installed after it: dpkg reports the epoch.
        self.assertTrue(app_update.newer("1.0.0", "1:0.9.0"))
        self.assertFalse(app_update.newer("0.9.0", "1:0.9.0"))
        self.assertFalse(app_update.newer("0.9.0", "1:1.0.0"))
        self.assertEqual(app_update.debian_version("0.9.0"), "1:0.9.0")
        self.assertEqual(app_update.debian_version("1:0.9.0"), "1:0.9.0")
        with patch.object(app_update.subprocess, "run", side_effect=OSError):
            self.assertTrue(app_update.newer("0.9.0", "2.5.1"))
            self.assertFalse(app_update.newer("0.9.0", "1:0.9.0"))

    def test_weekly_state(self):
        with tempfile.TemporaryDirectory() as cache, patch.dict(os.environ, {"XDG_CACHE_HOME": cache}):
            self.assertTrue(app_update.due())
            info = {"version": "2.2.0"}
            self.assertTrue(app_update.record(info, True, now=1000))
            self.assertFalse(app_update.record(info, True, now=2000), "notifies once per version")
            self.assertFalse(app_update.due(now=2000 + 3600))
            self.assertTrue(app_update.due(now=2000 + app_update.WEEK + 1))

    def test_only_https(self):
        with self.assertRaises(app_update.UpdateError):
            app_update._open("http://example.invalid/x.deb")

    def test_helper_refuses_bad_arguments_before_anything_else(self):
        for argv in ([], ["x.deb"], ["x.txt", DIGEST], ["x.deb", "nothex"]):
            result = subprocess.run([sys.executable, str(HELPER), *argv], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, argv)
            self.assertIn("usage", result.stderr)

    def test_helper_checks_the_hash_of_its_own_copy(self):
        if os.geteuid() != 0:
            self.skipTest("the helper runs as root")
        with tempfile.NamedTemporaryFile(suffix=".deb") as package:
            package.write(b"not a package")
            package.flush()
            result = subprocess.run([sys.executable, str(HELPER), package.name, DIGEST],
                                    capture_output=True, text=True)
            self.assertIn("checksum mismatch", result.stderr)
            good = hashlib.sha256(b"not a package").hexdigest()
            result = subprocess.run([sys.executable, str(HELPER), package.name, good],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("checksum", result.stderr)


WINDOW = r"""
import os, sys
sys.path.insert(0, sys.argv[1])
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Adw, GLib
Adw.init()
from galaxy_companion import window
win = window.CompanionWindow(None)
win.set_default_size(int(sys.argv[2]), 700)
win.present()
loop = GLib.MainLoop()
GLib.timeout_add(1500, loop.quit)
loop.run()
narrow = win.page_menu.get_visible()
opened = None
if narrow:
    win.page_menu.set_active(True)
    opened = win.split_view.get_show_sidebar()
    win.page_list.emit("row-activated", win.page_rows["haptics"])
    opened = opened and not win.split_view.get_show_sidebar() and win.view_stack.get_visible_child_name() == "haptics"
print(win.switcher_bar.get_visible(), narrow, len(win.page_rows), win.get_width(), opened)
"""


@unittest.skipUnless(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"), "needs a display")
class NarrowWindowTests(unittest.TestCase):
    def state(self, width):
        env = dict(os.environ, GALAXY_COMPANION_DEVICE="gts9uwifi")
        result = subprocess.run([sys.executable, "-c", WINDOW, str(PACKAGE), str(width)], env=env,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        bar, menu, items, actual, navigated = result.stdout.split()[-5:]
        self.navigated = navigated == "True"
        return bar == "True", menu == "True", int(items), int(actual)

    def test_wide_window_keeps_the_bottom_bar(self):
        bar, menu, items, _width = self.state(1100)
        self.assertEqual((bar, menu), (True, False))
        self.assertEqual(items, 6)

    def test_narrow_window_moves_pages_to_the_sidebar(self):
        bar, menu, _items, width = self.state(360)
        self.assertLess(width, 500)
        self.assertEqual((bar, menu), (False, True))
        # The hamburger opens the sidebar; picking a page shows it and closes the sidebar.
        self.assertTrue(self.navigated)


if __name__ == "__main__":
    unittest.main()
