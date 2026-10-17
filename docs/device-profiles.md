# Device profiles

`galaxy_companion/device.py` decides which device is running and what Galaxy
Companion may drive on it. The UI, the session backend
(`galaxy-companion-hardware`), the S Pen pairing service and the privileged
helpers (boot switch, updater, keyboard diagnostics) all read the same result.

A profile is a JSON file named after the device. It only describes hardware;
it never runs code. Profiles are searched in:

1. `/etc/galaxy-companion/devices/` for local overrides
2. `/usr/share/galaxy-companion/devices/`, shipped here or by a device port's own package

## A minimal profile

A phone with a vibration motor:

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

[`gts9uwifi.json`](../packaging/galaxy-companion/usr/share/galaxy-companion/devices/gts9uwifi.json)
is the complete example: S Pen sysfs attributes and Bluetooth, keyboard cover
models and their protocol IDs, flashlight helper, boot partitions, dual boot and
the port's release repository.

Without a profile the app still detects a vibration motor, fprintd and a Wacom
EMR digitizer. Features that need exact knowledge of the board (keyboard covers,
the S Pen silo, dual boot, updates) stay off rather than guess.

## Matching

1. `GALAXY_COMPANION_DEVICE=<id>` forces a profile (tests, trying a profile).
2. Otherwise the first profile whose `match.compatible` shares a string with
   `/sys/firmware/devicetree/base/compatible`.
3. Otherwise the first whose `match.model` equals the device tree `model`.
4. Otherwise the device is *generic*: its name is the device tree model, and it
   gets only auto-detected features.

Directories, highest precedence first; the first file seen for an `id` wins:
`$GALAXY_COMPANION_DEVICES_DIR`, `/etc/galaxy-companion/devices`,
`/usr/share/galaxy-companion/devices`. A device port can ship its profile in its
own package, under `/usr/share/galaxy-companion/devices/<id>.json`.

## Features

| Feature | What it enables | Auto-detected |
|---|---|---|
| `spen` | S Pen digitizer button events | Wacom EMR Digitizer input |
| `spen-dock` | silo attributes: docked, orientation, charging, hover rejection, digitizer off when docked | no |
| `spen-remote` | Bluetooth LE remote: air actions, pointer mode, battery, docked pairing | no |
| `keyboard-cover` | pogo Book Cover keyboards: special key remapping, diagnostics | no |
| `haptics` | FF_RUMBLE vibration motor: on-screen keyboard and notification feedback | known motor names |
| `fingerprint` | fprintd enrollment page | fprintd installed |
| `flashlight` | "Toggle the flashlight" action, through the device's helper | no |
| `dual-boot` | Android/Linux switching, with the Dualboot Android app ([dual-boot.md](dual-boot.md)) | no |
| `updates` | whole-port updates published as GitHub releases | no |
| `notification-led` | LED page: rules for a multicolour status LED (notifications per app, battery, charging, media), quiet hours | no |
| `charge-limit` | "Other" page: stop charging at a chosen level | no |
| `bixby-key` | "Other" page: single, double and long press of the Bixby button, with the S Pen's actions | no |

The S Pen page appears with `spen` plus `spen-dock` or `spen-remote`: a bare
digitizer has nothing to configure. A leading minus (`"-haptics"`) removes a
feature that would otherwise be detected.

## Fields

All sections are optional; only the ones a listed feature needs are read.

```jsonc
{
  "id": "gts9uwifi",                 // file name without .json
  "name": "Galaxy Tab S9 Ultra",     // shown in the UI
  "model": "SM-X910",
  "form_factor": "tablet",           // "phone" or "foldable": the home page icon
  "soc": "Qualcomm Snapdragon 8 Gen 2 for Galaxy (SM8550)",  // About → Details
  "match": {"compatible": ["samsung,gts9uwifi"], "model": ["Samsung Galaxy Tab S9 Ultra Wi-Fi"]},
  "features": ["spen", "spen-dock", "..."],
  "port": {"name": "...", "website": "...", "issues": "..."},  // About credits

  "spen": {
    "digitizer_input": "Wacom EMR Digitizer",  // evdev name with BTN_STYLUS
    "dock_attribute": "pen_docked",            // /sys/bus/i2c/devices/*/<this>
    "ble_reset_attribute": "pen_ble_reset",
    "battery_supply": "gts9u-spen",            // /sys/class/power_supply/<this>
    "pointer_aspect": 1.6                      // panel width / height
  },
  "keyboard_cover": {
    "input_prefix": "Book Cover Keyboard",     // evdev name the backend grabs
    "pogo_driver": "samsung-gts9u-stm32-pogo", // /sys/bus/i2c/drivers/<this>
    "firmware_service": "...", "firmware_file": "...",  // diagnostics only
    "models": [{"model": "EF-DX920", "name": "...", "protocol": 214,
                "ai_key": true, "touchpad": false}]
  },
  "haptics": {"vibrator_input": "gpio-vibrator", "fixed_intensity": true},
  "flashlight": {"led": "white:flash", "helper": "/usr/bin/gts9u-flashlight",
                 "schema": "io.github.agcarbajo.GTS9UFlashlight",
                 "icon": "gts9u-flashlight-symbolic"},
  "dual_boot": {"partitions": [{"name": "boot", "size": 100663296, "fallback": "/dev/sda21"},
                               "init_boot", "vendor_boot", "dtbo"],  // or just names
                "kernel_partition": "boot",
                "linux_root": "linuxroot",            // Linux's root, mounted by the Android app
                "android_devices": ["gts9uwifi"],     // ro.product.device
                "android_data": "userdata",
                "sets_dir": "/var/lib/gts9u-boot-sets",
                "backups_dir": "/var/lib/gts9u-boot-backups",
                "noask_rule": "/etc/polkit-1/rules.d/49-gts9u-boot-switch.rules"},
                // see dual-boot.md; a port with updates but no dual boot lists
                // its partitions as a top-level "boot_partitions" instead
  "notification_led": {"led": "rgb:status",          // /sys/class/leds/<this>
                       "default_trigger": "..."},   // given back when the rules are off
  "bixby_key": {"input": "gpio-keys", "code": 212},  // evdev name and key code; read, never grabbed
  "charge_limit": {"method": "charge-behaviour",     // or "threshold"
                   "battery": "max170xx_battery",    // /sys/class/power_supply/<this>
                   "charger": "max77705-charger",    // has charge_behaviour (that method)
                   "levels": [60, 65, 70, 75, 80, 85, 90, 95]},  // optional
  "updates": {"repository": "owner/repo", "device": "gts9uwifi",
              "identity_file": "/usr/lib/gts9u-release.json",
              "asset_pattern": "regex of the installation ZIP name",
              "format_marker": "gts9u-update-format",
              "bootstrap_asset": "gts9u-update.pyz",
              "root_label": "UBTS9U_UFS",
              "required_packages": ["ubuntu-gts9u-device", "ubuntu-gts9u-hardware"],
              "offline_unit": "gts9u-offline-update.service",
              "lock": "/run/lock/gts9u-boot.lock"}
}
```

`scripts/test-device-profiles.py` validates every shipped profile, the matching
rules and the pages the real window builds for each device.

## Vibration motors

`device.VIBRATOR_NAMES` and `70-galaxy-companion-uinput.rules` list the same motor
names, so the desktop user can open them: `gpio-vibrator`, `pwm-vibrator`,
`regulator-haptic`, `max77693-haptic`, `max77843-haptic`, `max8997-haptic`. A motor
with another name needs both a profile (`haptics.vibrator_input`) and a udev rule
from the device port granting the `input` group access.

## Adding a device

1. Write `<id>.json` with `match`, `name` and the features the port's kernel
   provides, and try it before packaging it:

   ```bash
   GALAXY_COMPANION_DEVICES_DIR=~/profiles galaxy-companion
   GALAXY_COMPANION_DEVICE=<id> galaxy-companion   # force this profile
   ```
2. Check About → Troubleshooting: it lists the profile file and the features.
3. Ship it in the port's package or send it here under
   `packaging/galaxy-companion/usr/share/galaxy-companion/devices/`, and add the
   device to `scripts/test-device-profiles.py`.

## Charge limit

Only list `charge-limit` once stopping the charge has been seen to work on the
device; a charger that ignores the request would make the option a lie.

- `threshold`: the kernel keeps the limit (`charge_control_end_threshold` on
  the battery, plus `charge_control_start_threshold` when present).
- `charge-behaviour`: the charger only accepts `inhibit-charge` / `auto`
  (`charge_behaviour`). `galaxy-companion-charge-limit.service` polls the
  battery every minute, stops at the limit and resumes 5 points below; stopping
  the service always resumes charging.

## Status LED

A multicolour LED class device (`multi_intensity`). The session backend picks
the first rule that holds and drives the LED through `galaxy-companion-led`:
steady, blinking (`timer` trigger) or breathing (`pattern` trigger, a slow
blink without it). Turning the rules off restores `default_trigger`.

With "Custom conditions" on (LED page → Advanced), two more situations exist:

- **A custom signal is on**: `galaxy-companion --led-signal NAME on|off` from
  any script (D-Bus `SetLedSignal` on the session backend). NAME is the signal
  name written in the rule (letters, digits, `-` and `_`). Signals live until
  logout.
- **A command succeeds**: the backend runs it with `sh -c` as the user every
  30-3600 s (10 s timeout); the rule holds while the last run exited 0.
