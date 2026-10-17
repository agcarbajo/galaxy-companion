# SPDX-License-Identifier: MIT
"""Reading, saving and replacing the partitions that decide which system boots.

Dual boot here means Android and Linux installed side by side on the internal
storage, sharing only the partitions that start them.  Which partitions those
are comes from the device profile (`dual_boot.partitions`): four on the Galaxy
Tab S9 Ultra (`boot`, `init_boot`, `vendor_boot`, `dtbo`), a single `boot` on
a device whose kernel and ramdisk live together.  Switching is writing one
saved copy of them -- a *set* -- and restarting.

Each set is a directory under `sets_dir` with one `<partition>.img` per
partition, a `kind` (linux or android) and an optional `name.txt`.  Nobody
types them in:

  * Linux saves its own set at every boot (`capture_running_linux`), because
    at that moment the partitions are by definition the ones that just
    started it.  A kernel update therefore reaches the set on the next boot.
  * The Android app does the same for Android, from Android, into this same
    directory on Linux's root filesystem.

See docs/dual-boot.md for the whole picture.  This module runs as root; the
window reaches it through the libexec helpers and polkit.
"""

import hashlib
import json
import os
import re
import shutil

from . import device


DEVICE = device.current()
_CONFIG = DEVICE.dual_boot if DEVICE.has("dual-boot") else {}

SETS_DIR = _CONFIG.get("sets_dir", "/var/lib/galaxy-companion/boot-sets")
# Where a replaced set is kept until the next one replaces it.  Outside
# SETS_DIR so that it is never mistaken for a system to boot.
BACKUPS_DIR = _CONFIG.get("backups_dir", SETS_DIR.rstrip("/") + "-backups")

# The rule that lets an active local session switch systems without a
# password.  galaxy-companion-boot-noask writes and removes it; it is named here
# so that the one place allowed to read it and the one place allowed to write
# it cannot drift apart.
NOASK_RULE = _CONFIG.get("noask_rule", "/etc/polkit-1/rules.d/49-galaxy-companion-boot-switch.rules")

# Android's userdata, whose size is all that can be read of it: a partition
# name ("userdata") or a kernel node ("sda34").
ANDROID_DATA = _CONFIG.get("android_data", _CONFIG.get("android_data_partition", ""))

# (name, size, fallback node).  A size of 0 means the partition's own size.
PARTITIONS = DEVICE.boot_partitions if _CONFIG else ()
_NAMES = [name for name, _size, _fallback in PARTITIONS]
# Written first, so that a switch interrupted half way never leaves the
# outgoing system's kernel in front of the incoming system's other images.
KERNEL = _CONFIG.get("kernel_partition") or ("boot" if "boot" in _NAMES else (_NAMES or [""])[0])

LINUX, ANDROID = "linux", "android"
SET_ID = re.compile(r"[A-Za-z0-9_-]{1,40}\Z")
_LINUX_WORDS = ("linux", "ubuntu", "debian", "fedora", "arch", "postmarket", "mobian")

# Last-resort names, deliberately without version numbers.  A real name comes
# from name.txt, written by whichever system is running; guessing a version
# here is how a tablet on One UI 7 ends up being told it runs One UI 8.
KNOWN_LABELS = {
    "ubuntu": "Ubuntu",
    "linux": "Linux",
    "android": "Android",
    "oneui": "Android",
    "lineage": "LineageOS",
    "lineageos": "LineageOS",
}


def available():
    return bool(PARTITIONS)


def ordered():
    """The partitions in the order a switch writes them: the kernel first."""
    return sorted(PARTITIONS, key=lambda part: part[0] != KERNEL)


def running_system_name():
    """What the system running right now calls itself."""
    try:
        with open("/etc/os-release", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


# -- partitions ---------------------------------------------------------------

def resolve_device(name):
    """The block device for a partition name.

    /dev/block/by-name is Android's convention, which some ports recreate;
    udev's by-partlabel is the Linux one.  The profile can still name the raw
    node for a board where neither exists.
    """
    fallback = next((fb for part, _size, fb in PARTITIONS if part == name), "")
    for path in (f"/dev/block/by-name/{name}", f"/dev/disk/by-partlabel/{name}", fallback):
        if path and os.path.exists(path):
            return path
    return None


def device_size(path):
    try:
        with open(path, "rb") as handle:
            return handle.seek(0, os.SEEK_END)
    except OSError:
        return 0


def sizes():
    """{partition: bytes}, or {} when any is missing or not the size the
    profile promises: a wrong partition must never be read as a right one."""
    out = {}
    for name, size, _fallback in PARTITIONS:
        path = resolve_device(name)
        actual = device_size(path) if path else 0
        if not actual or (size and actual != size):
            return {}
        out[name] = actual
    return out


def sha256(path, limit=None):
    digest = hashlib.sha256()
    remaining = limit
    with open(path, "rb") as handle:
        while True:
            size = 4 << 20 if remaining is None else min(4 << 20, remaining)
            if size <= 0:
                break
            chunk = handle.read(size)
            if not chunk:
                break
            digest.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return digest.hexdigest()


def live_hashes(lengths=None):
    lengths = sizes() if lengths is None else lengths
    if len(lengths) != len(PARTITIONS):
        return {}
    return {name: sha256(resolve_device(name), lengths[name]) for name, _size, _fb in PARTITIONS}


# -- sets ---------------------------------------------------------------------

def _read_line(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.readline().strip()
    except OSError:
        return ""


def kind_of(set_id, directory=None):
    """linux or android: from the set's `kind` file, else guessed from its id
    (sets written before the file existed are called "ubuntu" and "android")."""
    kind = _read_line(os.path.join(directory or os.path.join(SETS_DIR, set_id), "kind"))
    if kind in (LINUX, ANDROID):
        return kind
    return LINUX if any(word in set_id.lower() for word in _LINUX_WORDS) else ANDROID


def _label(set_id):
    line = _read_line(os.path.join(SETS_DIR, set_id, "name.txt"))
    if line and len(line) <= 40:
        return line
    return KNOWN_LABELS.get(set_id.lower(), set_id.capitalize())


def _set_hashes(directory, lengths):
    out = {}
    for name, _size, _fallback in PARTITIONS:
        path = os.path.join(directory, f"{name}.img")
        try:
            if name not in lengths or os.path.getsize(path) != lengths[name]:
                return {}
        except OSError:
            return {}
        out[name] = sha256(path)
    return out


def set_ids():
    try:
        return sorted(entry for entry in os.listdir(SETS_DIR)
                      if SET_ID.match(entry) and os.path.isdir(os.path.join(SETS_DIR, entry)))
    except OSError:
        return []


def discover(lengths=None):
    lengths = sizes() if lengths is None else lengths
    sets = []
    for set_id in set_ids():
        hashes = _set_hashes(os.path.join(SETS_DIR, set_id), lengths)
        sets.append({
            "id": set_id,
            "label": _label(set_id),
            "kind": kind_of(set_id),
            "complete": len(hashes) == len(PARTITIONS) and bool(hashes),
            "hashes": hashes,
        })
    return sets


def identify(live, sets):
    if not live or len(live) != len(PARTITIONS):
        return None
    for entry in sets:
        if entry["complete"] and all(live[name] == entry["hashes"][name] for name in live):
            return entry["id"]
    return None


def linux_set_id(sets=None):
    """The id of Linux's set: the one already saved, else "linux"."""
    ids = set_ids() if sets is None else [s["id"] for s in sets]
    return next((set_id for set_id in ids if kind_of(set_id) == LINUX), LINUX)


def recover_interrupted():
    """Puts back a set whose replacement was cut off between two renames."""
    try:
        entries = os.listdir(BACKUPS_DIR)
    except OSError:
        return
    for entry in entries:
        set_id = entry[:-len(".previous")] if entry.endswith(".previous") else ""
        target = os.path.join(SETS_DIR, set_id)
        if SET_ID.match(set_id) and not os.path.exists(target):
            os.makedirs(SETS_DIR, exist_ok=True)
            os.rename(os.path.join(BACKUPS_DIR, entry), target)


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _copy(source, target, length):
    with open(source, "rb") as src, open(target, "wb") as dst:
        remaining = length
        while remaining > 0:
            chunk = src.read(min(4 << 20, remaining))
            if not chunk:
                raise OSError(f"{source} ended early")
            dst.write(chunk)
            remaining -= len(chunk)
        dst.flush()
        os.fsync(dst.fileno())


def save_set(set_id, kind, name, lengths, expected):
    """Copies the live partitions into a set, replacing it in one rename.

    `expected` are the live hashes read before deciding to save; the copy has
    to match them and the partitions have to still match them afterwards, or
    nothing is replaced.  The set it replaces is kept in BACKUPS_DIR.
    """
    os.makedirs(SETS_DIR, exist_ok=True)
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    stage = os.path.join(BACKUPS_DIR, f"{set_id}.new")
    shutil.rmtree(stage, ignore_errors=True)
    os.mkdir(stage)
    try:
        for part, _size, _fallback in PARTITIONS:
            image = os.path.join(stage, f"{part}.img")
            _copy(resolve_device(part), image, lengths[part])
            if sha256(image) != expected[part]:
                raise OSError(f"{part} changed while it was being saved")
        with open(os.path.join(stage, "kind"), "w", encoding="utf-8") as handle:
            handle.write(kind + "\n")
        if name:
            with open(os.path.join(stage, "name.txt"), "w", encoding="utf-8") as handle:
                handle.write(name + "\n")
        if live_hashes(lengths) != expected:
            raise OSError("the boot partitions changed while they were being saved")
        _fsync_dir(stage)
        final = os.path.join(SETS_DIR, set_id)
        previous = os.path.join(BACKUPS_DIR, f"{set_id}.previous")
        if os.path.isdir(final):
            shutil.rmtree(previous, ignore_errors=True)
            os.rename(final, previous)
        os.rename(stage, final)
        _fsync_dir(SETS_DIR)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def _stamp(set_id, name, kind):
    """Writes name.txt and kind when they say something else."""
    directory = os.path.join(SETS_DIR, set_id)
    for filename, value in (("name.txt", name), ("kind", kind)):
        if value and _read_line(os.path.join(directory, filename)) != value:
            try:
                with open(os.path.join(directory, filename), "w", encoding="utf-8") as handle:
                    handle.write(value + "\n")
            except OSError:
                pass


def capture_running_linux(report=lambda *_args, **_kw: None):
    """Saves the running Linux's boot partitions as its set.  Run at boot.

    Early in boot nothing has written the boot partitions since the
    bootloader read them, so they *are* this Linux's, whatever they hash to:
    no guessing about kernels is needed.  Only a set that is already Android's
    is refused -- that would mean Linux started from images saved as Android,
    and overwriting them could lose Android's.
    """
    if not available():
        return False
    recover_interrupted()
    lengths = sizes()
    live = live_hashes(lengths)
    if not live:
        report("error", "partitions-missing")
        return False
    sets = discover(lengths)
    name = running_system_name()
    current = identify(live, sets)
    if current is not None:
        kind = kind_of(current)
        if kind == ANDROID:
            report("error", "running-from-android-set", set=current)
            return False
        _stamp(current, name, LINUX)
        report("done", "linux-unchanged", set=current)
        return True
    set_id = linux_set_id(sets)
    save_set(set_id, LINUX, name, lengths, live)
    report("done", "linux-saved", set=set_id)
    return True


# -- status -------------------------------------------------------------------

def _partition_bytes(node):
    """Size of a partition, from sysfs, in bytes.

    /sys reports in 512-byte sectors no matter what the disk's logical sector
    size is, which on UFS is 4096 -- so the number here is eight times the
    GPT's, and multiplying by 512 is what puts it back.
    """
    try:
        with open(f"/sys/class/block/{node}/size", "r", encoding="ascii") as handle:
            return int(handle.read().strip()) * 512
    except (OSError, ValueError):
        return 0


def _node(partition):
    """sda34 for "sda34" or for a partition whose label is "userdata"."""
    if os.path.exists(f"/sys/class/block/{partition}"):
        return partition
    for path in (f"/dev/disk/by-partlabel/{partition}", f"/dev/block/by-name/{partition}"):
        if os.path.exists(path):
            return os.path.basename(os.path.realpath(path))
    return ""


def storage():
    """How much room each system has, and how much of it is used.

    Linux's own usage comes from the filesystem it is running on.  Android's
    cannot be read from here at all: its userdata is encrypted, so only the
    size of the partition is honest, and the UI says so rather than inventing
    a number.
    """
    info = {}
    try:
        stat = os.statvfs("/")
        total = stat.f_blocks * stat.f_frsize
        free = stat.f_bavail * stat.f_frsize
        info[LINUX] = {"total": total, "used": total - free, "known": True}
    except OSError:
        pass
    node = _node(ANDROID_DATA) if ANDROID_DATA else ""
    android_total = _partition_bytes(node) if node else 0
    if android_total:
        info[ANDROID] = {"total": android_total, "used": 0, "known": False}
    return info


def noask_enabled():
    """Whether switching systems currently skips the password prompt.

    This has to be answered from root.  /etc/polkit-1/rules.d is root:polkitd
    and 0750, so the unprivileged window cannot see the rule even when it is
    installed, and asking polkit instead would not do: the switch action is
    auth_admin_keep, so a recent password would make polkit answer "allowed"
    for a few minutes and the window would report a setting nobody turned on.
    """
    return os.path.exists(NOASK_RULE)


def status():
    """What the window shows.  Read-only: saving is the boot service's job."""
    lengths = sizes()
    live = live_hashes(lengths)
    sets = discover(lengths)
    return {
        "current": identify(live, sets),
        "partitions": [name for name, _size, _fallback in ordered()],
        "readable": bool(live),
        "sets": [{"id": s["id"], "label": s["label"], "kind": s["kind"], "complete": s["complete"]}
                 for s in sets],
        "storage": storage(),
        "noask": noask_enabled(),
    }


# -- switching ----------------------------------------------------------------

def unsaved(live, sets):
    """Partitions whose live contents are in no saved set.

    Writing over them would destroy the only copy -- typically a kernel
    update installed since this Linux booted, which is saved on the next
    boot.  A partition that matches any set is fine, which is what lets a
    switch that stopped half way be run again.
    """
    return [name for name in live
            if not any(s["complete"] and s["hashes"][name] == live[name] for s in sets)]


def write_set(set_id, report):
    """Writes one set, verifying every partition by reading it back.

    Nothing reboots here.  A caller that has seen a failure must be able to
    stop: a device with some partitions replaced still runs the system it is
    on, but only until it is restarted.
    """
    recover_interrupted()
    lengths = sizes()
    sets = discover(lengths)
    entry = next((s for s in sets if s["id"] == set_id), None)
    if entry is None or not entry["complete"]:
        report("error", "incomplete", set=set_id)
        return False
    live = live_hashes(lengths)
    if not live:
        report("error", "partitions-missing")
        return False
    missing = unsaved(live, sets)
    if missing:
        report("error", "unsaved", parts=missing)
        return False

    for name, _size, _fallback in ordered():
        target = resolve_device(name)
        source = os.path.join(SETS_DIR, set_id, f"{name}.img")
        report("step", "writing", part=name)
        if live[name] != entry["hashes"][name]:
            try:
                _copy(source, target, lengths[name])
            except OSError as error:
                report("error", "write-failed", part=name, detail=str(error))
                return False
        if sha256(target, lengths[name]) != entry["hashes"][name]:
            report("error", "mismatch", part=name)
            return False
        report("step", "verified", part=name)

    report("done", "written", set=set_id)
    return True


# English for logs and for anything that reads the helper without the window.
MESSAGES = {
    "writing": "Writing {part}…",
    "verified": "{part} verified.",
    "written": "The boot partitions now hold {set}.",
    "rebooting": "Restarting…",
    "incomplete": "The {set} set is missing or incomplete.",
    "partitions-missing": "The boot partitions cannot be read.",
    "unsaved": "{parts} hold images that are not saved anywhere. Restart Linux once so it saves them, then switch.",
    "write-failed": "Could not write {part}: {detail}",
    "mismatch": "{part} does not match when read back. Do not restart: check it first.",
    "busy": "An update or a system switch is already running.",
    "update-pending": "Install or cancel the prepared update before switching systems.",
    "missing-argument": "Say which system to switch to.",
    "linux-saved": "Saved this Linux's boot partitions as {set}.",
    "linux-unchanged": "{set} is already saved.",
    "running-from-android-set": "Linux started from the images saved as {set}; nothing was saved.",
}


def emit(kind, code, **args):
    """One JSON object per line, so the window can follow progress as it
    happens and translate it: `code` and its arguments, plus English."""
    values = {key: ", ".join(value) if isinstance(value, list) else value for key, value in args.items()}
    try:
        message = MESSAGES.get(code, code).format(**values)
    except (KeyError, IndexError):
        message = code
    print(json.dumps({"kind": kind, "code": code, **args, "message": message}), flush=True)
