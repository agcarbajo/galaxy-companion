# Galaxy Companion

Native GNOME settings application for Samsung Galaxy phones and tablets running a
mainline Linux kernel, with Ubuntu and GNOME as the first target.

It shows a page for each piece of hardware the device has (S Pen, keyboard cover,
vibration motor, fingerprint reader, status LED, dual boot, system updates), a
home page with the device name, model, processor and memory, and other options
such as a battery charge limit where the device supports them.

## Compatible devices

- Galaxy Tab S9 Ultra (SM-X910)
- Galaxy S9+ (SM-G965F)

Other devices run with the features that can be detected without a profile.

## Dual boot

On devices where Android and Linux are installed side by side, Galaxy Companion
and the **Dualboot** Android app in [`android/dualboot`](android/dualboot) restart
into either system from the other. Each system saves its own boot partitions:
after installing Linux, start it once, then open the app on Android. See
[docs/dual-boot.md](docs/dual-boot.md).

Download the [Android Dualboot 1.0.0 APK](https://github.com/agcarbajo/galaxy-companion/releases/download/v1.0.0/galaxy-companion-dualboot_1.0.0.apk).
**Uninstall the old Dualboot app first**, then install this APK and grant root.
Removing the old app does not remove Ubuntu or its files. For the Tab S9 Ultra's
Ubuntu 24.04 upgrade, follow the [port's update guide](https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra#updating-an-existing-installation).


## Updates

Galaxy Companion updates itself from this repository's releases, separately
from the device's port: the home page checks for a newer
`galaxy-companion_<version>_all.deb`, verifies it against the release's
`SHA256SUMS` and installs it through polkit (`galaxy-companion-self-update`).
With weekly checks on, it also sends a notification. The Dualboot Android app
updates itself the same way, from the signed APK in the same releases.
`scripts/publish-release.sh` runs the tests, builds both and publishes them.

The device's port is updated from the **Updates** page when its profile has an
`updates` section: the port publishes build ZIPs as GitHub releases, and the
page downloads one, verifies it, stages its packages and matching boot images,
and installs them after a restart with the previous boot set and modules kept
for recovery. A ZIP whose manifest declares an **Ubuntu release upgrade** is
not applied by Galaxy Companion itself: it hands off to the migration backend
the ZIP carries (`UPDATE/updater.pyz`), either because the ZIP is the port's
published release or because the user confirmed a local file by its complete
SHA-256. The contract a port's backend has to meet is in
[docs/galaxy-companion.md](docs/galaxy-companion.md#system-updates).

## Adding a device

Each supported device has a small JSON profile describing its hardware. To add
yours, see [docs/device-profiles.md](docs/device-profiles.md), and
[docs/dual-boot.md](docs/dual-boot.md#adding-a-device) for dual boot.

## License

MIT.

Galaxy Companion began as Tab Companion, part of the
[Ubuntu port for the Galaxy Tab S9 Ultra](https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra).
