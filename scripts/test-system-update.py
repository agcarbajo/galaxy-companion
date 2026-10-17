#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline application safety tests on temporary files; never touches a device.

The tests use the Galaxy Tab S9 Ultra profile for its partition table, but the
code under test reads everything device-specific from the profile."""
import os as _os
_os.environ.setdefault("GALAXY_COMPANION_DEVICE", "gts9uwifi")
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                      "packaging/galaxy-companion/usr/lib/galaxy-companion"))
from galaxy_companion import update_bundle as b
from galaxy_companion import update_core as c


class OfflineTransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.transaction = self.root / "transaction"
        self.transaction.mkdir()
        self.marker = self.root / "system-update"
        self.marker.symlink_to(self.transaction)
        self.identity = self.root / "identity.json"
        self.saved = self.root / "saved-linux"
        self.old = b"old boot".ljust(32, b"\0")
        self.new = b"new boot".ljust(32, b"\0")
        self.devices = {}
        for part in b.PARTITIONS:
            device = self.root / ("device-" + part)
            device.write_bytes(self.old)
            self.devices[part] = device
            (self.transaction / (part + ".img")).write_bytes(self.new)
        self.plan = {"format": 1, "suite": "noble", "files": {p + ".img": {"sha256": hashlib.sha256(self.new).hexdigest()}
                                for p in b.PARTITIONS}, "apt_packages": [],
                     "device": b.DEVICE_ID, "version": "1.1.0", "tag": "v1.1.0", "kernel_release": "test"}
        (self.transaction / "plan.json").write_text(json.dumps(self.plan))
        (self.transaction / "archives.json").write_text("{}")
        (self.root / "dpkg-status").write_text("installed packages")
        (self.transaction / "dpkg.sha256").write_text(b.sha256(self.root / "dpkg-status"))
        self.patches = [patch.object(c, "STATE", self.root), patch.object(c, "TRANSACTION", self.transaction),
            patch.object(c, "MARKER", self.marker), patch.object(b, "IDENTITY", self.identity),
            patch.dict(b.PARTITIONS, {p: 32 for p in b.PARTITIONS}),
            patch.object(c, "device_check"), patch.object(c, "power_check"),
            patch.object(c, "saved_set", return_value=self.saved),
            patch.object(c.policy, "ubuntu_suite", return_value="noble"),
            patch.object(c, "partitions", return_value=self.devices),
            patch.object(c.subprocess, "run", return_value=subprocess.CompletedProcess([], 3))]
        real_sha = b.sha256
        self.patches.append(patch.object(b, "sha256", side_effect=lambda p: real_sha(
            self.root / "dpkg-status" if str(p) == "/var/lib/dpkg/status" else p)))
        for p in self.patches:
            p.start()
        c.set_status("ready", tag="v1.1.0")
        self.commands = []

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def execute(self, argv, capture=False, offline=False):
        self.commands.append(argv)
        if argv[:2] == ["cp", "-a"]:
            source, dest = argv[2:]
            if source in ("/etc", "/usr/lib/modules"):
                Path(dest).mkdir()
                (Path(dest) / "preserved").write_text("user settings / old modules")
        return ""

    def test_complete_updates_boot_and_saved_set_only(self):
        with patch.object(c, "run", side_effect=self.execute):
            c.apply_offline()
        self.assertEqual(c.status()["state"], "complete")
        self.assertFalse(self.marker.is_symlink())
        self.assertEqual(json.loads(self.identity.read_text())["tag"], "v1.1.0")
        for part, device in self.devices.items():
            self.assertEqual(device.read_bytes(), self.new)
            self.assertEqual((self.transaction / "backup" / (part + ".img")).read_bytes(), self.old)
            self.assertEqual((self.saved / (part + ".img")).read_bytes(), self.new)
        self.assertEqual((self.saved / "kind").read_text().strip(), "linux")
        self.assertIn(["systemctl", "--no-block", "reboot"], self.commands)

    def test_package_changes_abort_before_writes(self):
        (self.root / "dpkg-status").write_text("changed since preparation")
        with patch.object(c, "run", side_effect=self.execute):
            c.apply_offline()
        self.assertEqual(c.status()["state"], "failed")
        self.assertFalse(any(a[0] == "apt-get" for a in self.commands))
        self.assertTrue(all(d.read_bytes() == self.old for d in self.devices.values()))

    def test_completed_transaction_is_not_rolled_back_after_power_loss(self):
        c.set_status("complete", tag="v1.1.0")
        with patch.object(c, "run", side_effect=self.execute):
            c.apply_offline()
        self.assertEqual(c.status()["state"], "complete")
        self.assertFalse(self.marker.is_symlink())
        self.assertEqual(self.commands, [["systemctl", "--no-block", "reboot"]])

    def test_failed_second_boot_write_restores_all_partitions(self):
        real_copy = c.copy_partition
        count = 0
        def failing_copy(src, dst, size):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("simulated I/O error")
            return real_copy(src, dst, size)
        with patch.object(c, "run", side_effect=self.execute), patch.object(c, "copy_partition", side_effect=failing_copy):
            c.apply_offline()
        self.assertEqual(c.status()["state"], "failed")
        self.assertTrue(all(d.read_bytes() == self.old for d in self.devices.values()))
        self.assertFalse(self.identity.exists())
        self.assertFalse(self.marker.is_symlink())

    def test_corrupted_staging_aborts_before_apt(self):
        (self.transaction / "boot.img").write_bytes(b"corrupt")
        with patch.object(c, "run", side_effect=self.execute):
            c.apply_offline()
        self.assertEqual(c.status()["state"], "failed")
        self.assertFalse(any(a[0] == "apt-get" for a in self.commands))
        self.assertTrue(all(d.read_bytes() == self.old for d in self.devices.values()))

    def test_apt_failure_keeps_old_boot_and_backup(self):
        def fail_apt(argv, *args, **kwargs):
            if argv[0] == "apt-get":
                raise OSError("simulated package failure")
            return self.execute(argv, *args, **kwargs)
        with patch.object(c, "run", side_effect=fail_apt):
            c.apply_offline()
        self.assertEqual(c.status()["state"], "failed")
        self.assertTrue((self.transaction / "backup/complete").exists())
        self.assertTrue(all(d.read_bytes() == self.old for d in self.devices.values()))
        # Whatever APT unpacked is configured before the old boot set returns.
        self.assertIn(["dpkg", "--force-confold", "--configure", "-a"], self.commands)

    def test_configure_failure_is_reported_without_emergency_mode(self):
        def fail_apt_and_dpkg(argv, *args, **kwargs):
            if argv[0] in ("apt-get", "dpkg"):
                raise OSError("simulated " + argv[0] + " failure")
            return self.execute(argv, *args, **kwargs)
        with patch.object(c, "run", side_effect=fail_apt_and_dpkg):
            c.apply_offline()
        status = c.status()
        self.assertEqual(status["state"], "failed")
        self.assertIn("package configuration incomplete", status["error"])
        self.assertNotIn("boot restore failed", status["error"])
        self.assertTrue(all(d.read_bytes() == self.old for d in self.devices.values()))
        self.assertNotIn(["systemctl", "--no-block", "start", "emergency.target"], self.commands)


class CommandLineTests(unittest.TestCase):
    def test_local_trust_requires_zip_and_exact_digest(self):
        for argv in (["--latest", "--trust-local-sha256", "a" * 64],
                     ["--zip", "x.zip", "--trust-local-sha256", "A" * 64],
                     ["--zip", "x.zip", "--trust-local-sha256", "abc"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                c.main(argv)

    def test_capabilities_advertise_confirmed_local_handoff(self):
        value = c.policy.capabilities()
        self.assertTrue(value["confirmed_local_release_backend_handoff"])
        self.assertIn("confirmed-local-release-backend-handoff", value["capabilities"])
        self.assertFalse(value["distribution_migration"])

    def test_handoff_variable_is_generic(self):
        self.assertEqual(c.HANDOFF_ENV, "GALAXY_COMPANION_HANDOFF_SHA256")


if __name__ == "__main__":
    unittest.main()
