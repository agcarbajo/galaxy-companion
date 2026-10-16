# Galaxy Companion

Native GNOME settings application for Samsung Galaxy phones and tablets running a
mainline Linux kernel, with Ubuntu and GNOME as the first target.

It started as **Tab Companion**, the companion app of the
[Galaxy Tab S9 Ultra Ubuntu port](https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra),
and was extracted here with its full history. Every Tab Companion feature is kept;
what was written for one tablet now comes from a **device profile**, so the same
application runs on other Samsung devices and shows only the pages their hardware
supports.

| Page | Needs | Galaxy Tab S9 Ultra | Galaxy S9+ | Device without a profile |
|---|---|:-:|:-:|:-:|
| S Pen: hover rejection, silo, air actions, pointer mode | `spen` + `spen-dock` / `spen-remote` | ✓ | | |
| Keyboard cover special keys and diagnostics | `keyboard-cover` | ✓ | | |
| Vibration: on-screen keyboard and notifications | `haptics` | ✓ | ✓ | if a known motor is found |
| Fingerprints (fprintd) | `fingerprint` | ✓ | | if fprintd is installed |
| Dual boot with Android | `dual-boot` | ✓ | | |
| Port updates | `updates` | ✓ | | |

A device where nothing is found gets a single page that says so, instead of empty tabs.

## Device profiles

A profile is a JSON file named after the device, matched against the device tree
(`/sys/firmware/devicetree/base/compatible`, then `model`). It only describes
hardware; it never runs code. Profiles are searched in:

1. `/etc/galaxy-companion/devices/` for local overrides
2. `/usr/share/galaxy-companion/devices/`, shipped here or by a device port's own package

The smallest useful profile, for a phone with a vibration motor:

```json
{
  "id": "star2lte",
  "name": "Galaxy S9+",
  "model": "SM-G965F",
  "form_factor": "phone",
  "soc": "Samsung Exynos 9810",
  "match": {"compatible": ["samsung,star2lte"], "model": ["Samsung Galaxy S9+ (SM-G965F)"]},
  "features": ["haptics"],
  "haptics": {"vibrator_input": "max77693-haptic", "fixed_intensity": false}
}
```

[`gts9uwifi.json`](packaging/galaxy-companion/usr/share/galaxy-companion/devices/gts9uwifi.json)
is the complete example: S Pen sysfs attributes and Bluetooth, keyboard cover models
and their protocol IDs, flashlight helper, boot partitions, dual boot and the port's
release repository. [docs/device-profiles.md](docs/device-profiles.md) describes
every field.

Without a profile the app still detects a vibration motor (`gpio-vibrator`,
`pwm-vibrator`, `max77693-haptic`, …), fprintd and a Wacom EMR digitizer. Features
that need exact knowledge of the board (keyboard covers, the S Pen silo, dual boot,
updates) stay off rather than guess. A profile can also switch a detected feature
off with a leading minus, for example `"-haptics"`.

To try a profile before packaging it:

```bash
GALAXY_COMPANION_DEVICES_DIR=~/profiles galaxy-companion
GALAXY_COMPANION_DEVICE=star2lte galaxy-companion   # force one profile
```

About → Troubleshooting shows which profile was used and the resulting features.

## Repository layout

- `packaging/galaxy-companion/`: the Debian package tree (app, backend, services, profiles)
- `scripts/build-companion-package.sh`: builds `galaxy-companion_<version>_all.deb`
- `scripts/test-*.py`: tests; `ci/run-tests.sh` runs all of them plus the package
  build in an Ubuntu 24.04 container (GTK 4, libadwaita, headless) from any host with Docker
- `docs/`: design notes, profiles, and the migration from Tab Companion

## Coming from Tab Companion

`galaxy-companion` replaces `ubuntu-gts9u-companion` (Provides/Replaces/Breaks) and
keeps its settings. What the Tab S9 Ultra port has to change to ship it is listed
in [docs/migrating-from-tab-companion.md](docs/migrating-from-tab-companion.md).

## License

MIT.
