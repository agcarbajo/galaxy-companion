# SPDX-License-Identifier: MIT
"""Which Samsung device this is, and what hardware Galaxy Companion may drive.

Everything that used to be written for one tablet lives in a device profile:
a JSON file named after the device, matched against the device tree.  A
profile only describes; it never runs anything.  Profiles are read from, in
order of precedence:

  /etc/galaxy-companion/devices/       local overrides
  /usr/share/galaxy-companion/devices/ shipped with this package or added by a
                                       device port's own package

A device without a profile still gets every feature that can be found
without one (vibration motor, fingerprint reader, a Wacom digitizer); the
features that need exact knowledge of the board -- keyboard covers, the S Pen
silo, dual boot, port updates -- stay off rather than guess.

GALAXY_COMPANION_DEVICE=<id> forces a profile and
GALAXY_COMPANION_DEVICES_DIR=<dir> adds a directory searched first; both exist
for tests and for trying a profile on a device before packaging it.

This module is plain Python with no GObject, so the backend, the privileged
helpers and the UI can all import it.
"""

from dataclasses import dataclass, field
from glob import glob
import json
import os
from pathlib import Path


SYSTEM_DIRS = (
    Path("/etc/galaxy-companion/devices"),
    Path("/usr/share/galaxy-companion/devices"),
)
# The tree this file is in, so tests and an uninstalled checkout find the
# profiles that sit next to the package in the repository.
_SOURCE_DIR = Path(__file__).resolve().parents[3] / "share/galaxy-companion/devices"
DT_ROOT = Path("/sys/firmware/devicetree/base")

FEATURES = (
    "spen",            # S Pen digitizer: hover rejection, button actions
    "spen-dock",       # silo with dock/orientation/charging attributes
    "spen-remote",     # Bluetooth remote: air actions and pointer mode
    "keyboard-cover",  # pogo-pin Book Cover keyboards and their special keys
    "haptics",         # force-feedback vibration motor
    "fingerprint",     # fprintd reader
    "flashlight",      # camera flash LED driven by a device helper
    "dual-boot",       # Android/Linux boot partition swapping
    "updates",         # whole-port updates published by the port
    "notification-led",  # RGB status LED driven by user rules
    "charge-limit",    # stop charging at a chosen battery level
)

# Input device names that are a vibration motor driven through FF_RUMBLE.
# The udev rule that opens them to the desktop user carries the same list.
VIBRATOR_NAMES = (
    "gpio-vibrator", "pwm-vibrator", "regulator-haptic",
    "max77693-haptic", "max77843-haptic", "max8997-haptic",
)
DIGITIZER_NAMES = ("Wacom EMR Digitizer",)
FPRINTD_SERVICE = "/usr/share/dbus-1/system-services/net.reactivated.Fprint.service"


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    model: str = ""
    form_factor: str = "tablet"
    soc: str = ""
    features: frozenset = frozenset()
    spen: dict = field(default_factory=dict)
    keyboard_cover: dict = field(default_factory=dict)
    haptics: dict = field(default_factory=dict)
    flashlight: dict = field(default_factory=dict)
    boot_partitions: tuple = ()
    dual_boot: dict = field(default_factory=dict)
    updates: dict = field(default_factory=dict)
    notification_led: dict = field(default_factory=dict)
    charge_limit: dict = field(default_factory=dict)
    port: dict = field(default_factory=dict)
    profile_path: str = ""

    def has(self, feature):
        return feature in self.features

    @property
    def generic(self):
        return not self.profile_path


def _read(path):
    try:
        return Path(path).read_bytes()
    except OSError:
        return b""


def device_tree(root=DT_ROOT):
    """(compatible strings, model) of the running board, empty off DT systems."""
    compatible = tuple(
        item.decode("ascii", "replace")
        for item in _read(Path(root) / "compatible").split(b"\0") if item
    )
    model = _read(Path(root) / "model").rstrip(b"\0").decode("utf-8", "replace").strip()
    return compatible, model


def profile_dirs():
    dirs = []
    extra = os.environ.get("GALAXY_COMPANION_DEVICES_DIR")
    if extra:
        dirs.append(Path(extra))
    dirs.extend(SYSTEM_DIRS)
    dirs.append(_SOURCE_DIR)
    return dirs


def load_profiles():
    """Every readable profile, the first directory winning for each id."""
    profiles = {}
    for directory in profile_dirs():
        for path in sorted(Path(directory).glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict) or not isinstance(data.get("id"), str):
                continue
            data["profile_path"] = str(path)
            profiles.setdefault(data["id"], data)
    return profiles


def match_profile(profiles, compatible, model):
    """The profile whose match rules name this board; compatible wins over model."""
    forced = os.environ.get("GALAXY_COMPANION_DEVICE")
    if forced:
        return profiles.get(forced)
    for data in profiles.values():
        rules = data.get("match", {})
        if set(rules.get("compatible", ())) & set(compatible):
            return data
    for data in profiles.values():
        if model and model in data.get("match", {}).get("model", ()):
            return data
    return None


def input_names():
    return [
        _read(Path(event) / "device/name").decode("utf-8", "replace").strip()
        for event in sorted(glob("/sys/class/input/event*"))
    ]


def autodetect(names=None):
    """Features that can be found without knowing the board."""
    names = input_names() if names is None else names
    found = set()
    if any(name in VIBRATOR_NAMES or "vibrator" in name.lower() for name in names):
        found.add("haptics")
    if any(name in DIGITIZER_NAMES for name in names):
        found.add("spen")
    if os.path.exists(FPRINTD_SERVICE):
        found.add("fingerprint")
    return found


def _generic_name(model):
    # "Samsung Galaxy S9+ (SM-G965F)" is already a good name; a bare SoC
    # board name is not, but it is still better than nothing.
    return model or "Samsung Galaxy"


def build(data, compatible=(), model="", detected=frozenset()):
    """A Device from a profile (or None for a generic device) plus detection."""
    if data is None:
        return Device(
            id="generic",
            name=_generic_name(model),
            form_factor="tablet" if "tablet" in model.lower() else "phone",
            features=frozenset(detected),
        )
    declared = set(data.get("features", ()))
    # A profile may switch auto-detected features off ("-haptics"), for a
    # board whose motor exists but must not be used.
    disabled = {item[1:] for item in declared if item.startswith("-")}
    declared = {item for item in declared if not item.startswith("-")}
    features = (declared | set(detected)) - disabled
    return Device(
        id=data["id"],
        name=data.get("name") or _generic_name(model),
        model=data.get("model", ""),
        form_factor=data.get("form_factor", "tablet"),
        soc=data.get("soc", ""),
        features=frozenset(feature for feature in features if feature in FEATURES),
        spen=data.get("spen", {}),
        keyboard_cover=data.get("keyboard_cover", {}),
        haptics=data.get("haptics", {}),
        flashlight=data.get("flashlight", {}),
        boot_partitions=tuple(
            (part["name"], int(part["size"]), part.get("fallback", ""))
            for part in data.get("boot_partitions", ())
        ),
        dual_boot=data.get("dual_boot", {}),
        updates=data.get("updates", {}),
        notification_led=data.get("notification_led", {}),
        charge_limit=data.get("charge_limit", {}),
        port=data.get("port", {}),
        profile_path=data.get("profile_path", ""),
    )


_current = None


def current(refresh=False):
    """The running device, read once per process."""
    global _current
    if _current is None or refresh:
        compatible, model = device_tree()
        data = match_profile(load_profiles(), compatible, model)
        _current = build(data, compatible, model, autodetect())
    return _current
