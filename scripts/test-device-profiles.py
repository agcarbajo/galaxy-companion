#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Device profiles: matching, auto-detection, overrides, and the pages each gets."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packaging/galaxy-companion/usr/lib/galaxy-companion"
PROFILES = ROOT / "packaging/galaxy-companion/usr/share/galaxy-companion/devices"
sys.path.insert(0, str(PACKAGE))
from galaxy_companion import device  # noqa: E402


def board(directory, compatible=(), model=""):
    """A fake /sys/firmware/devicetree/base."""
    root = Path(directory) / "dt"
    root.mkdir()
    (root / "compatible").write_bytes(b"".join(c.encode() + b"\0" for c in compatible))
    (root / "model").write_bytes(model.encode() + b"\0")
    return root


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ)
        self.env.start()
        os.environ.pop("GALAXY_COMPANION_DEVICE", None)
        os.environ.pop("GALAXY_COMPANION_DEVICES_DIR", None)
        self.temp = tempfile.TemporaryDirectory()
        # Only the profiles in this checkout, never ones installed on the host.
        self.dirs = patch.object(device, "SYSTEM_DIRS", ())
        self.dirs.start()

    def tearDown(self):
        self.dirs.stop()
        self.env.stop()
        self.temp.cleanup()

    def resolve(self, compatible=(), model="", names=()):
        compatible_read, model_read = device.device_tree(board(self.temp.name, compatible, model))
        data = device.match_profile(device.load_profiles(), compatible_read, model_read)
        with patch.object(device.os.path, "exists", return_value=False):
            detected = device.autodetect(list(names))
        return device.build(data, compatible_read, model_read, detected)

    def test_every_shipped_profile_is_valid(self):
        for path in PROFILES.glob("*.json"):
            data = json.loads(path.read_text())
            self.assertEqual(path.stem, data["id"], path)
            self.assertTrue(data["match"].get("compatible") or data["match"].get("model"), path)
            unknown = {f.lstrip("-") for f in data.get("features", ())} - set(device.FEATURES)
            self.assertFalse(unknown, path)
            for model in data.get("keyboard_cover", {}).get("models", ()):
                self.assertTrue(model["model"] and model["name"], path)
            if "updates" in data.get("features", ()):
                self.assertTrue(data["updates"]["repository"] and device.boot_partitions(data), path)
            if "dual-boot" in data.get("features", ()):
                # What the Android app needs to find this device and Linux's root.
                dual = data["dual_boot"]
                self.assertTrue(dual["partitions"] and dual["linux_root"] and dual["android_devices"], path)

    def test_tab_s9_ultra_by_compatible(self):
        found = self.resolve(("qcom,kalama-mtp", "qcom,kalama", "qcom,mtp", "samsung,gts9uwifi", "qcom,sm8550"),
                             "Samsung Galaxy Tab S9 Ultra Wi-Fi")
        self.assertEqual(found.id, "gts9uwifi")
        self.assertFalse(found.generic)
        for feature in ("spen", "spen-dock", "spen-remote", "keyboard-cover", "haptics",
                        "dual-boot", "updates"):
            self.assertTrue(found.has(feature), feature)
        self.assertEqual(dict((n, s) for n, s, _ in found.boot_partitions)["init_boot"], 8388608)

    def test_galaxy_s9_plus_is_a_phone_with_haptics_led_and_charge_limit(self):
        found = self.resolve(("samsung,star2lte", "samsung,exynos9810"), "Samsung Galaxy S9+ (SM-G965F)",
                             names=["max77693-haptic", "gpio-keys"])
        self.assertEqual((found.id, found.form_factor), ("star2lte", "phone"))
        self.assertEqual(found.features, frozenset({"haptics", "notification-led", "charge-limit", "bixby-key"}))
        self.assertEqual(found.notification_led["led"], "rgb:status")

    def test_model_string_matches_when_compatible_does_not(self):
        found = self.resolve(("vendor,other",), "Samsung Galaxy S9+ (SM-G965F)")
        self.assertEqual(found.id, "star2lte")

    def test_unknown_device_gets_only_what_it_can_detect(self):
        found = self.resolve(("samsung,a52q", "qcom,sm7125"), "Samsung Galaxy A52",
                             names=["pwm-vibrator", "Wacom EMR Digitizer", "Book Cover Keyboard"])
        self.assertTrue(found.generic)
        self.assertEqual(found.name, "Samsung Galaxy A52")
        # A cover keyboard name alone is not enough to drive one.
        self.assertEqual(found.features, frozenset({"haptics", "spen"}))
        self.assertEqual(found.boot_partitions, ())

    def test_boot_partitions_by_name_or_with_size(self):
        self.assertEqual(device.boot_partitions({"dual_boot": {"partitions": ["boot"]}}), (("boot", 0, ""),))
        self.assertEqual(device.boot_partitions({"dual_boot": {"partitions": [
            {"name": "boot", "size": 4096, "fallback": "/dev/sda1"}, "dtbo", 7]}}),
            (("boot", 4096, "/dev/sda1"), ("dtbo", 0, "")))
        # A port with updates but no dual boot still lists them at the top.
        self.assertEqual(device.boot_partitions({"boot_partitions": [{"name": "boot", "size": 1}]}),
                         (("boot", 1, ""),))

    def test_unknown_device_without_hardware_has_no_features(self):
        found = self.resolve((), "")
        self.assertTrue(found.generic)
        self.assertEqual(found.features, frozenset())

    def test_local_override_wins_and_can_disable_detected_features(self):
        override = Path(self.temp.name) / "etc"
        override.mkdir()
        (override / "star2lte.json").write_text(json.dumps({
            "id": "star2lte", "name": "Custom S9+",
            "match": {"compatible": ["samsung,star2lte"]}, "features": ["-haptics"]}))
        os.environ["GALAXY_COMPANION_DEVICES_DIR"] = str(override)
        found = self.resolve(("samsung,star2lte",), names=["max77693-haptic"])
        self.assertEqual(found.name, "Custom S9+")
        self.assertFalse(found.has("haptics"))

    def test_forced_device(self):
        os.environ["GALAXY_COMPANION_DEVICE"] = "gts9uwifi"
        self.assertEqual(self.resolve(("samsung,star2lte",)).id, "gts9uwifi")

    def test_broken_profiles_are_skipped(self):
        broken = Path(self.temp.name) / "broken"
        broken.mkdir()
        (broken / "bad.json").write_text("{not json")
        (broken / "noid.json").write_text("{}")
        os.environ["GALAXY_COMPANION_DEVICES_DIR"] = str(broken)
        self.assertEqual(set(device.load_profiles()), {p.stem for p in PROFILES.glob("*.json")})


PAGES = r"""
import os, sys
sys.path.insert(0, sys.argv[1])
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Adw
Adw.init()
from galaxy_companion import device, window
pages = window.CompanionWindow(None).view_stack.get_pages()
print(",".join(pages.get_item(i).get_name() for i in range(pages.get_n_items())))
"""


@unittest.skipUnless(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"), "needs a display")
class WindowPageTests(unittest.TestCase):
    """The real window, built for each device in a fresh process."""

    def pages(self, device_id, devices_dir=None):
        env = dict(os.environ, GALAXY_COMPANION_DEVICE=device_id)
        if devices_dir:
            env["GALAXY_COMPANION_DEVICES_DIR"] = devices_dir
        result = subprocess.run([sys.executable, "-c", PAGES, str(PACKAGE)], env=env,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        return result.stdout.strip().splitlines()[-1].split(",")

    def test_tab_s9_ultra_pages(self):
        pages = self.pages("gts9uwifi")
        # Dual boot also needs its helpers installed under /usr/libexec.
        # No LED and no confirmed charge limit: neither page, and no "Other".
        expected = ["home", "pen", "keyboard", "haptics", "fingerprint", "updates"]
        self.assertEqual([p for p in pages if p != "dualboot"], expected)

    def test_galaxy_s9_plus_pages(self):
        pages = self.pages("star2lte")
        self.assertEqual(pages, ["home", "haptics", "led", "other"])
        for absent in ("pen", "keyboard", "dualboot", "updates"):
            self.assertNotIn(absent, pages)

    def test_device_with_nothing_shows_only_home(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "bare.json").write_text(json.dumps({
                "id": "bare", "name": "Galaxy Test", "match": {"compatible": ["x,none"]},
                "features": ["-haptics", "-fingerprint", "-spen"]}))
            self.assertEqual(self.pages("bare", directory), ["home"])


if __name__ == "__main__":
    unittest.main()
