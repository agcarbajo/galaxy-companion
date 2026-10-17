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

## Updates

Galaxy Companion updates itself from this repository's releases, separately
from the device's port: the home page checks for a newer
`galaxy-companion_<version>_all.deb`, verifies it against the release's
`SHA256SUMS` and installs it through polkit (`galaxy-companion-self-update`).
With weekly checks on, it also sends a notification. `scripts/publish-release.sh`
runs the tests, builds the package and publishes both files.

## Adding a device

Each supported device has a small JSON profile describing its hardware. To add
yours, see [docs/device-profiles.md](docs/device-profiles.md), and
[docs/dual-boot.md](docs/dual-boot.md#adding-a-device) for dual boot.

## License

MIT.

Galaxy Companion began as Tab Companion, part of the
[Ubuntu port for the Galaxy Tab S9 Ultra](https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra).
