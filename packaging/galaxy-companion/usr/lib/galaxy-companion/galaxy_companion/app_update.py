# SPDX-License-Identifier: MIT
"""Updates of Galaxy Companion itself, independent of the device's port.

Each release of this repository carries `galaxy-companion_<version>_all.deb`
and a `SHA256SUMS` that lists it.  This module finds the newest one, downloads
it into the user's cache and checks its hash; installing it is the job of
`/usr/libexec/galaxy-companion-self-update`, run through pkexec, which checks
the hash again on its own root-only copy.  Nothing here is privileged.
"""
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import DEBIAN_VERSION, EPOCH, VERSION

REPOSITORY = "agcarbajo/galaxy-companion"
API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
PACKAGE = "galaxy-companion"
HELPER = "/usr/libexec/galaxy-companion-self-update"
ASSET = re.compile(r"galaxy-companion_([0-9][A-Za-z0-9.+~-]{0,60})_all\.deb\Z")
SUMS = "SHA256SUMS"
MAX_DEB = 64 * 1024**2
MAX_METADATA = 1024**2
HEX = re.compile(r"[0-9a-f]{64}\Z")
WEEK = 7 * 24 * 60 * 60


class UpdateError(Exception):
    pass


def _open(url):
    if urllib.parse.urlsplit(url).scheme != "https":
        raise UpdateError("Only HTTPS downloads are supported")
    response = urllib.request.urlopen(urllib.request.Request(url, headers={
        "User-Agent": f"GalaxyCompanion/{VERSION}", "Accept": "application/vnd.github+json",
    }), timeout=60)
    # A redirect to plain HTTP would undo the check above.
    if urllib.parse.urlsplit(response.url).scheme != "https":
        response.close()
        raise UpdateError("The download was redirected away from HTTPS")
    return response


def _read(url, limit=MAX_METADATA):
    with _open(url) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError("The server answered with more data than expected")
    return data


def installed():
    """The installed package version; the module's own when run from source."""
    try:
        result = subprocess.run(["dpkg-query", "-W", "-f=${Version}", PACKAGE],
                                capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return DEBIAN_VERSION


def debian_version(version):
    """A release's version (the asset name carries no epoch) as the Debian
    version its package has."""
    return version if ":" in version else EPOCH + ":" + version


def _key(version):
    """A fallback ordering for hosts without dpkg: numbers compare as numbers."""
    epoch, _, rest = version.rpartition(":")
    upstream = re.split(r"[~+-]", rest, maxsplit=1)[0]
    return [int(epoch or 0)] + [int(part) if part.isdigit() else part for part in re.split(r"[.]", upstream)]


def newer(candidate, current):
    """Whether release `candidate` is newer than the installed `current`.

    `current` is dpkg's view of the installed package: with the epoch on the
    current scheme, without it on the 1.x and 2.x packages that predate the
    restart at 0.9.0, which is exactly what ranks the restart above them."""
    candidate = debian_version(candidate)
    try:
        return subprocess.run(["dpkg", "--compare-versions", candidate, "gt", current],
                              timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        try:
            return _key(candidate) > _key(current)
        except TypeError:
            return False


def parse_sums(text):
    sums = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and HEX.match(parts[0].lower()):
            sums[parts[1].lstrip("*")] = parts[0].lower()
    return sums


def parse_release(release, sums_text):
    """The installable package a release describes, or an UpdateError."""
    assets = {asset.get("name"): asset for asset in release.get("assets", ()) if isinstance(asset, dict)}
    debs = [(ASSET.match(name or ""), asset) for name, asset in assets.items()]
    debs = [(match.group(1), asset) for match, asset in debs if match]
    if len(debs) != 1:
        raise UpdateError("The latest release does not carry exactly one Galaxy Companion package")
    version, asset = debs[0]
    digest = parse_sums(sums_text).get(asset["name"])
    if not digest:
        raise UpdateError("SHA256SUMS does not list the package")
    size = int(asset.get("size") or 0)
    if not 0 < size <= MAX_DEB:
        raise UpdateError("The package has an unexpected size")
    return {
        "version": version,
        "tag": release.get("tag_name") or version,
        "notes": release.get("body") or "",
        "page": release.get("html_url") or "",
        "name": asset["name"],
        "url": asset["browser_download_url"],
        "size": size,
        "sha256": digest,
    }


def latest():
    release = json.loads(_read(API))
    sums = next((asset for asset in release.get("assets", ()) if asset.get("name") == SUMS), None)
    if sums is None:
        raise UpdateError("The latest release has no SHA256SUMS")
    return parse_release(release, _read(sums["browser_download_url"]).decode("utf-8", "replace"))


def check():
    """(info, available) for the newest release against what is installed."""
    info = latest()
    return info, newer(info["version"], installed())


def cache_dir():
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "galaxy-companion" / "app-update"


def _state_path():
    return cache_dir().parent / "app-update.json"


def load_state():
    try:
        value = json.loads(_state_path().read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(value):
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value))
    os.replace(temp, path)


def due(now=None):
    """Whether the weekly check should ask GitHub again."""
    now = time.time() if now is None else now
    last = load_state().get("checked_at", 0)
    return not isinstance(last, (int, float)) or not 0 <= now - last < WEEK


def record(info, available, now=None):
    """Remember a weekly check; True when this version deserves a notification."""
    value = load_state()
    value["checked_at"] = time.time() if now is None else now
    notify = available and value.get("notified") != info["version"]
    if notify:
        value["notified"] = info["version"]
    save_state(value)
    return notify


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def download(info, progress=None):
    """The verified package in the user's cache."""
    directory = cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    for old in directory.glob("*.deb"):
        old.unlink(missing_ok=True)
    target = directory / info["name"]
    partial = target.with_suffix(".part")
    done = 0
    with _open(info["url"]) as response, open(partial, "wb") as stream:
        while block := response.read(256 * 1024):
            done += len(block)
            if done > info["size"]:
                raise UpdateError("The package is larger than the release says")
            stream.write(block)
            if progress:
                progress(done, info["size"])
    if done != info["size"] or sha256(partial) != info["sha256"]:
        partial.unlink(missing_ok=True)
        raise UpdateError("The downloaded package does not match its checksum")
    partial.replace(target)
    return target


def install(path, digest):
    """Install through pkexec; returns (ok, message)."""
    try:
        result = subprocess.run(["pkexec", HELPER, str(path), digest],
                                capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    if result.returncode in (126, 127):
        return False, "cancelled"
    message = (result.stderr or result.stdout).strip().splitlines()
    return result.returncode == 0, message[-1] if message else ""
