# Migrating from Tab Companion

Galaxy Companion 2.0.0 is Tab Companion 1.5.5 renamed and made device-generic.
On the Galaxy Tab S9 Ultra it behaves the same: the `gts9uwifi` profile turns on
every feature Tab Companion had.

## What carries over by itself

- **Settings.** The GSettings schema is now `io.github.agcarbajo.GalaxyCompanion`,
  but its dconf path is still `/io/github/agcarbajo/TabCompanion/`, so every mapping,
  gesture and preference stays.
- **S Pen remote switch.** `postinst` copies `/var/lib/tab-companion/spen-remote-enabled`
  to `/var/lib/galaxy-companion/`.
- **Keyboard haptics extension.** It is now `galaxy-companion-haptics@agcarbajo`;
  the session enabler replaces the old UUID in `enabled-extensions`.
- **"Switch without the password".** `postinst` rewrites an existing rule to the
  renamed polkit action (`io.github.agcarbajo.GalaxyCompanion.boot-switch`).
- **Package.** `galaxy-companion` Provides, Replaces and Breaks
  `ubuntu-gts9u-companion (<< 2.0~)`, so apt swaps one for the other.
- **Updates.** The updater accepts bundles that carry either package name.

## What the Tab S9 Ultra port has to change

These are in [ubuntu-galaxy-tab-s9-ultra](https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra),
not here, and nothing breaks until the port switches packages.

1. **Build and install `galaxy-companion`** instead of `ubuntu-gts9u-companion`:
   build the `.deb` from this repository (`scripts/build-companion-package.sh`) and
   change the package list in `scripts/build-ubuntu-rootfs.sh`. Then remove
   `packaging/ubuntu-gts9u-companion/` and its tests from the port.
2. **Fingerprint overlay.** `gts9u-fingerprint-overlay@agcarbajo/authKeyboard.js`
   recognises the forwarding keyboard by name. It is now
   `Galaxy Companion virtual keyboard`; accept both names during the transition.
3. **Update bootstrap.** `scripts/build-update-payload.py` freezes the updater
   modules into `gts9u-update.pyz`. `update_core` and `update_bundle` now import
   `device.py` and need the `gts9uwifi` profile: add both to the zipapp, and set
   `GALAXY_COMPANION_DEVICE=gts9uwifi` (or ship the profile) where it runs.
4. **`scripts/update-to-latest.py`** downloads the updater from the port's own
   repository, so it stays in the port and keeps pointing at the old package paths
   until step 1 is done.
5. **Optional:** move `gts9uwifi.json` into `ubuntu-gts9u-device`. Two packages
   cannot own the same file, so it has to leave this repository in the same
   release; until then the copy shipped here is the one used.
