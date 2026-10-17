#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Dual boot on the Linux side, against files standing in for the partitions.

A throwaway profile names two partitions (`boot`, `dtbo`) whose fallback
nodes are plain files, and a sets directory in a temporary tree, so saving,
identifying and switching run for real without a block device in sight.
"""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packaging/galaxy-companion/usr/lib/galaxy-companion"
LIBEXEC = ROOT / "packaging/galaxy-companion/usr/libexec"
sys.path.insert(0, str(PACKAGE))
from galaxy_companion import device  # noqa: E402

SIZE = {"boot": 64 * 1024, "dtbo": 16 * 1024}


class Rig:
    """A temporary device: profile, partitions and sets directory."""

    def __init__(self, partitions=("boot", "dtbo"), sized=True):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "profiles").mkdir()
        (self.root / "dev").mkdir()
        self.sets = self.root / "sets"
        self.backups = self.root / "backups"
        listed = []
        for name in partitions:
            node = self.root / "dev" / name
            node.write_bytes(b"\0" * SIZE[name])
            entry = {"name": name, "fallback": str(node)}
            if sized:
                entry["size"] = SIZE[name]
            listed.append(entry)
        profile = {
            "id": "testboot", "name": "Test", "match": {"compatible": ["test,boot"]},
            "features": ["dual-boot"],
            "dual_boot": {"partitions": listed, "linux_root": "linuxroot",
                          "android_devices": ["testboot"],
                          "sets_dir": str(self.sets), "backups_dir": str(self.backups)},
        }
        (self.root / "profiles/testboot.json").write_text(json.dumps(profile))
        self.env = {"GALAXY_COMPANION_DEVICES_DIR": str(self.root / "profiles"),
                    "GALAXY_COMPANION_DEVICE": "testboot"}
        os.environ.update(self.env)
        device.current(refresh=True)
        from galaxy_companion import boot_core
        self.core = importlib.reload(boot_core)
        self.core.running_system_name = lambda: "Ubuntu 24.04.3 LTS"

    def close(self):
        for key in self.env:
            os.environ.pop(key, None)
        device.current(refresh=True)
        self.tmp.cleanup()

    def flash(self, name, fill):
        """Puts recognisable contents on a partition, as a bootloader would see it."""
        (self.root / "dev" / name).write_bytes(fill * SIZE[name])

    def read(self, name):
        return (self.root / "dev" / name).read_bytes()

    def save(self, set_id, kind, fills):
        directory = self.sets / set_id
        directory.mkdir(parents=True)
        for name, fill in fills.items():
            (directory / f"{name}.img").write_bytes(fill * SIZE[name])
        if kind:
            (directory / "kind").write_text(kind + "\n")


class DualBootTests(unittest.TestCase):
    def setUp(self):
        self.rig = Rig()
        self.core = self.rig.core
        self.events = []

    def tearDown(self):
        self.rig.close()

    def report(self, kind, code, **args):
        self.events.append((kind, code, args))

    def test_partitions_come_from_the_profile_with_the_kernel_first(self):
        self.assertTrue(self.core.available())
        self.assertEqual(self.core.KERNEL, "boot")
        self.assertEqual([p[0] for p in self.core.ordered()], ["boot", "dtbo"])
        self.assertEqual(self.core.sizes(), SIZE)

    def test_linux_saves_itself_at_boot(self):
        self.rig.flash("boot", b"L")
        self.rig.flash("dtbo", b"l")
        self.assertTrue(self.core.capture_running_linux(self.report))
        saved = self.rig.sets / "linux"
        self.assertEqual((saved / "boot.img").read_bytes(), self.rig.read("boot"))
        self.assertEqual((saved / "kind").read_text().strip(), "linux")
        self.assertEqual((saved / "name.txt").read_text().strip(), "Ubuntu 24.04.3 LTS")
        status = self.core.status()
        self.assertEqual(status["current"], "linux")
        self.assertEqual(status["partitions"], ["boot", "dtbo"])
        self.assertEqual(status["sets"], [{"id": "linux", "label": "Ubuntu 24.04.3 LTS",
                                           "kind": "linux", "complete": True}])

    def test_an_unchanged_set_is_not_rewritten(self):
        self.rig.flash("boot", b"L")
        self.core.capture_running_linux(self.report)
        image = self.rig.sets / "linux/boot.img"
        before = image.stat().st_ino
        self.core.capture_running_linux(self.report)
        self.assertEqual(image.stat().st_ino, before)
        self.assertEqual(self.events[-1][1], "linux-unchanged")

    def test_a_new_kernel_replaces_the_set_and_keeps_the_old_one(self):
        self.rig.save("ubuntu", None, {"boot": b"L", "dtbo": b"l"})  # an older set, no kind file
        self.rig.flash("boot", b"K")
        self.rig.flash("dtbo", b"l")
        self.assertTrue(self.core.capture_running_linux(self.report))
        self.assertEqual((self.rig.sets / "ubuntu/boot.img").read_bytes()[:1], b"K")
        self.assertEqual((self.rig.backups / "ubuntu.previous/boot.img").read_bytes()[:1], b"L")
        self.assertFalse((self.rig.sets / "linux").exists())

    def test_android_set_is_never_overwritten_by_linux(self):
        self.rig.save("android", "android", {"boot": b"A", "dtbo": b"a"})
        self.rig.flash("boot", b"A")
        self.rig.flash("dtbo", b"a")
        self.assertFalse(self.core.capture_running_linux(self.report))
        self.assertEqual(self.events[-1][1], "running-from-android-set")
        self.assertFalse((self.rig.sets / "linux").exists())

    def test_an_interrupted_replacement_is_put_back(self):
        self.rig.save("linux", "linux", {"boot": b"L", "dtbo": b"l"})
        self.rig.backups.mkdir()
        os.rename(self.rig.sets / "linux", self.rig.backups / "linux.previous")
        self.core.recover_interrupted()
        self.assertTrue((self.rig.sets / "linux/boot.img").exists())

    def test_switch_writes_every_partition_and_verifies(self):
        self.rig.save("linux", "linux", {"boot": b"L", "dtbo": b"l"})
        self.rig.save("android", "android", {"boot": b"A", "dtbo": b"a"})
        self.rig.flash("boot", b"L")
        self.rig.flash("dtbo", b"l")
        self.assertTrue(self.core.write_set("android", self.report))
        self.assertEqual(self.rig.read("boot")[:1], b"A")
        self.assertEqual(self.rig.read("dtbo")[:1], b"a")
        steps = [(code, args.get("part")) for _kind, code, args in self.events]
        self.assertEqual(steps[:2], [("writing", "boot"), ("verified", "boot")])
        self.assertEqual(self.core.status()["current"], "android")

    def test_switch_refuses_to_destroy_unsaved_partitions(self):
        self.rig.save("linux", "linux", {"boot": b"L", "dtbo": b"l"})
        self.rig.save("android", "android", {"boot": b"A", "dtbo": b"a"})
        self.rig.flash("boot", b"K")   # a kernel installed since this Linux booted
        self.rig.flash("dtbo", b"l")
        self.assertFalse(self.core.write_set("android", self.report))
        self.assertEqual(self.events[-1][:2], ("error", "unsaved"))
        self.assertEqual(self.events[-1][2]["parts"], ["boot"])
        self.assertEqual(self.rig.read("boot")[:1], b"K")

    def test_a_half_finished_switch_can_be_run_again(self):
        self.rig.save("linux", "linux", {"boot": b"L", "dtbo": b"l"})
        self.rig.save("android", "android", {"boot": b"A", "dtbo": b"a"})
        self.rig.flash("boot", b"A")   # stopped after the kernel
        self.rig.flash("dtbo", b"l")
        self.assertTrue(self.core.write_set("android", self.report))
        self.assertEqual(self.rig.read("dtbo")[:1], b"a")

    def test_kind_falls_back_to_the_id(self):
        self.rig.save("ubuntu", None, {"boot": b"L", "dtbo": b"l"})
        self.rig.save("oneui", None, {"boot": b"A", "dtbo": b"a"})
        kinds = {s["id"]: (s["kind"], s["label"]) for s in self.core.discover()}
        self.assertEqual(kinds, {"ubuntu": ("linux", "Ubuntu"), "oneui": ("android", "Android")})
        self.assertEqual(self.core.linux_set_id(), "ubuntu")

    def test_wrong_sized_images_make_a_set_incomplete(self):
        self.rig.save("android", "android", {"boot": b"A"})
        (self.rig.sets / "android/dtbo.img").write_bytes(b"a" * 10)
        self.assertFalse(self.core.discover()[0]["complete"])
        self.assertFalse(self.core.write_set("android", self.report))
        self.assertEqual(self.events[-1][1], "incomplete")

    def test_status_reports_storage_keys_for_both_systems(self):
        self.assertIn("linux", self.core.status()["storage"])

    def test_messages_have_english_and_codes(self):
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out):
            self.core.emit("error", "unsaved", parts=["boot", "dtbo"])
        event = json.loads(out.getvalue())
        self.assertEqual(event["code"], "unsaved")
        self.assertTrue(event["message"].startswith("boot, dtbo hold images"))

    @unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0, "the boot lock is root's")
    def test_capture_helper_end_to_end(self):
        os.makedirs("/run/lock", exist_ok=True)
        self.rig.flash("boot", b"L")
        result = subprocess.run([sys.executable, str(LIBEXEC / "galaxy-companion-boot-capture")],
                                capture_output=True, text=True, env={**os.environ, **self.rig.env})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout.splitlines()[-1])["code"], "linux-saved")
        self.assertTrue((self.rig.sets / "linux/boot.img").exists())


class UnsizedTests(unittest.TestCase):
    """A device whose profile only names its single boot partition."""

    def test_size_comes_from_the_partition(self):
        rig = Rig(partitions=("boot",), sized=False)
        try:
            self.assertEqual(rig.core.PARTITIONS, (("boot", 0, str(rig.root / "dev/boot")),))
            self.assertEqual(rig.core.sizes(), {"boot": SIZE["boot"]})
            rig.flash("boot", b"L")
            self.assertTrue(rig.core.capture_running_linux())
            rig.save("android", "android", {"boot": b"A"})
            self.assertTrue(rig.core.write_set("android", lambda *a, **k: None))
            self.assertEqual(rig.read("boot")[:1], b"A")
        finally:
            rig.close()

    def test_a_partition_of_the_wrong_size_is_refused(self):
        rig = Rig(partitions=("boot",))
        try:
            (rig.root / "dev/boot").write_bytes(b"\0" * 10)
            self.assertEqual(rig.core.sizes(), {})
            self.assertFalse(rig.core.capture_running_linux())
        finally:
            rig.close()


class WindowTextTests(unittest.TestCase):
    def test_switch_events_are_translated_by_code(self):
        from galaxy_companion import boot_sets
        self.assertEqual(boot_sets.describe({"code": "writing", "part": "boot"}), "Writing boot…")
        self.assertIn("boot, dtbo", boot_sets.describe({"code": "unsaved", "parts": ["boot", "dtbo"]}))
        self.assertEqual(boot_sets.describe({"message": "from an older helper"}), "from an older helper")

    def test_icons_follow_the_kind(self):
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from galaxy_companion.window import CompanionWindow as Window
        self.assertEqual(Window._icon_for({"id": "x", "kind": "linux"}), "computer-symbolic")
        self.assertEqual(Window._icon_for({"id": "ubuntu"}), "computer-symbolic")
        self.assertEqual(Window._icon_for({"id": "lineage", "kind": "android"}), "phone-symbolic")


if __name__ == "__main__":
    unittest.main()
