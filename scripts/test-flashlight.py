#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The flashlight helper against a fake LED, and the profiles that use it."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packaging/galaxy-companion"
HELPER = PACKAGE / "usr/libexec/galaxy-companion-flashlight"
EXTENSION = PACKAGE / "usr/share/gnome-shell/extensions/flashlight@agcarbajo.github.io"


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.led = Path(self.temp.name) / "white:flash"
        self.led.mkdir()
        (self.led / "brightness").write_text("0\n")
        (self.led / "max_brightness").write_text("255\n")

    def run_helper(self, *args, device="star2lte"):
        env = dict(os.environ, GALAXY_COMPANION_LEDS=self.temp.name, GALAXY_COMPANION_DEVICE=device)
        return subprocess.run([sys.executable, str(HELPER), *args], capture_output=True, text=True, env=env)

    def level(self):
        return int((self.led / "brightness").read_text())

    def test_on_off_toggle_status(self):
        self.assertEqual(self.run_helper("on", "200").returncode, 0)
        self.assertEqual(self.level(), 200)
        self.assertEqual(self.run_helper("status").stdout.strip(), "on")
        self.run_helper("off")
        self.assertEqual(self.level(), 0)
        self.run_helper("toggle")
        self.assertEqual(self.level(), 128, "the default level")
        self.run_helper("toggle")
        self.assertEqual(self.level(), 0)
        self.assertEqual(self.run_helper("path").stdout.strip(), str(self.led))

    def test_levels_follow_the_leds_own_maximum(self):
        (self.led / "max_brightness").write_text("15\n")
        self.run_helper("on", "255")
        self.assertEqual(self.level(), 15)
        self.run_helper("on", "1")
        self.assertEqual(self.level(), 1, "never 0 when on")

    def test_bad_requests_change_nothing(self):
        for args in (("on", "0"), ("on", "256"), ("on", "x"), ("off", "1"), ("strobe",)):
            self.assertNotEqual(self.run_helper(*args).returncode, 0, args)
        self.assertEqual(self.level(), 0)

    def test_no_torch_no_flashlight(self):
        result = self.run_helper("status", device="none")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no flashlight", result.stderr)


class ProfileTests(unittest.TestCase):
    def test_profiles_with_a_torch(self):
        devices = PACKAGE / "usr/share/galaxy-companion/devices"
        s9 = json.loads((devices / "star2lte.json").read_text())
        self.assertIn("flashlight", s9["features"])
        self.assertEqual(s9["flashlight"], {"led": "white:flash"}, "Galaxy Companion's own helper")
        tab = json.loads((devices / "gts9uwifi.json").read_text())
        self.assertEqual(tab["flashlight"]["helper"], "/usr/bin/gts9u-flashlight", "the Tab keeps its own")

    def test_extension_metadata(self):
        meta = json.loads((EXTENSION / "metadata.json").read_text())
        self.assertEqual(meta["uuid"], EXTENSION.name)
        self.assertIn("46", meta["shell-version"])
        source = (EXTENSION / "extension.js").read_text()
        self.assertIn("/usr/libexec/galaxy-companion-flashlight", source)
        self.assertIn("io.github.agcarbajo.GalaxyCompanion.Flashlight", source)


if __name__ == "__main__":
    unittest.main()
