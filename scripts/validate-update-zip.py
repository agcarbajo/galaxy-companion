#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify the safe-update contract and every payload byte before publishing."""
import hashlib
from pathlib import Path
import sys
import zipfile

import json
import os

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                      "packaging/galaxy-companion/usr/lib/galaxy-companion"))

# This runs where the release is built, not on the device, so the profile is
# the one the manifest names rather than whatever this machine is.
if len(sys.argv) > 1 and "GALAXY_COMPANION_DEVICE" not in os.environ:
    try:
        with zipfile.ZipFile(sys.argv[1]) as _archive:
            os.environ["GALAXY_COMPANION_DEVICE"] = json.loads(
                _archive.read("UPDATE/manifest.json")).get("device", "")
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        pass
from galaxy_companion.update_bundle import inspect  # noqa: E402


def validate(path):
    manifest = inspect(path)
    with zipfile.ZipFile(path) as archive:
        for name, entry in manifest["files"].items():
            digest = hashlib.sha256()
            with archive.open(name) as source:
                for chunk in iter(lambda: source.read(4 * 1024**2), b""):
                    digest.update(chunk)
            if digest.hexdigest() != entry["sha256"]:
                raise ValueError("Update payload checksum mismatch: " + name)
    print("PASS update payload", manifest["tag"])


if __name__ == "__main__":
    validate(sys.argv[1])
