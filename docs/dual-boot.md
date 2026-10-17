# Dual boot

Android and Linux installed side by side on the internal storage, switched
from either system without a PC, a bootloader menu or a second boot slot.
Galaxy Companion does the Linux half; the **Dualboot** Android app in
[`android/dualboot`](../android/dualboot) does the Android half. Both read the
same [device profile](device-profiles.md).

## How it works

A Samsung bootloader always starts whatever is on the boot partitions. Android
and Linux each need their own contents there and nothing else in common:
Android keeps its system in `super` and its data in `userdata`, and Linux keeps
its root filesystem on a partition of its own. So switching is just:

1. write the other system's saved copy of the boot partitions;
2. read every partition back and compare it with the copy;
3. restart.

Nothing is moved, resized or formatted, so a switch takes seconds and cannot
lose data. Which partitions are the boot partitions depends on the device and
is in its profile: four on the Galaxy Tab S9 Ultra (`boot`, `init_boot`,
`vendor_boot`, `dtbo`), a single `boot` on a device whose kernel and ramdisk
live together.

| Partition | Holds | Written on a switch |
|---|---|---|
| the profile's `partitions` | kernel, ramdisks, device tree | yes |
| `super` | Android's system and vendor | never |
| `userdata` | Android's apps and files | never |
| the profile's `linux_root` | Linux's root filesystem (and the saved sets) | never |
| `vbmeta` | verified boot descriptors | never |

`vbmeta` is never touched: Linux needs it with verification disabled (flags 2),
Android runs fine with that, and rewriting it changes the key Android derives
for its encrypted `/data`, which costs a wipe of Android's data every time.

`super` is not switched either, so two Android ROMs cannot both be installed.
The pairing is Linux plus whichever Android is installed; installing another
ROM simply replaces the Android side.

### Saved sets

Each system's copy of the boot partitions is a *set*, a directory on Linux's
root filesystem:

```
<sets_dir>/                       /var/lib/galaxy-companion/boot-sets by default
├── linux/
│   ├── boot.img                  one image per partition, exactly its size
│   ├── kind                      "linux" or "android"
│   └── name.txt                  what the system calls itself, e.g. "Ubuntu 24.04.3 LTS"
└── android/
    └── …
<backups_dir>/<id>.previous/      the copy each set replaced, kept until the next one
```

Linux's root filesystem is the only place both systems can reach: Android's
`/data` is encrypted, but Android with root can mount Linux's ext4 partition.
Sets saved by hand under `/sdcard/BootSets/<id>/` on Android are also read
there, and win over the saved one.

Nobody types the images in. Each system saves its own:

- **Linux** saves its set at every boot (`galaxy-companion-boot-capture.service`,
  before anyone can log in). At that moment nothing has written the boot
  partitions since the bootloader read them, so they are, by definition, the
  ones that started this Linux. A kernel update therefore reaches the saved
  set at the next boot, and a port update refreshes it straight away. The only
  thing it refuses is overwriting the set saved as Android's.
- **Android**: the Dualboot app saves Android's set when the device finishes
  booting, when the app is opened or updated, and before every switch. It
  creates the set the first time and replaces it when Android changes (an OTA
  update, Magisk patching the boot image). It only saves after proving the
  kernel on the boot partition is the running Android kernel (Magisk's
  `magiskboot`, or the boot image header and a search for
  `Linux version <uname -r>`), and never when any partition holds Linux's
  images: that is a switch waiting for a restart, or one that stopped half way.

### Switching

From Linux: the Dualboot page in Galaxy Companion, or its quick settings
button. Reading is allowed without a password; switching asks for one through
polkit, unless *Switch systems without the password* is on.

From Android: the Dualboot app, or its quick settings tile. *Switch on next
restart* writes the partitions and stops; *Restart* also restarts. Root is
required (Magisk, KernelSU…).

Both sides write the kernel partition first, verify each partition by reading
it back, and stop without restarting if anything does not match. Linux also
refuses to overwrite a partition whose contents are in no saved set, such as a
kernel installed since it booted: restart Linux once and it is saved. A switch
that stopped half way can simply be run again.

## Setting it up the first time

1. **Install Linux** with the device port's installer, on its own partition.
   Android's `userdata` must stay Android's: a port that puts Linux in
   `userdata` (like the Galaxy S9+ one) cannot dual boot.
2. **Start Linux once.** It saves its own boot partitions as the `linux` set.
   A port installer can also do this for it by putting the images in
   `<sets_dir>/linux/` with `kind` set to `linux`.
3. **Go back to Android**: restore Android's boot images from recovery, or
   flash an Android ROM. Neither touches Linux's partition.
4. **On Android, with root, install and open Dualboot.** It finds Linux's
   partition, saves Android's boot partitions as the `android` set, and lists
   both systems. Tap *Restart* on Linux.

From then on either system restarts into the other, and an update on either
side keeps its own set current without anyone doing anything. If the app says
Linux has not saved its partitions yet, step 2 was skipped.

## Adding a device

Everything device specific is in its profile
(`packaging/galaxy-companion/usr/share/galaxy-companion/devices/<id>.json`).
The Android app is built with the same files, so one file covers both sides:

```jsonc
"features": ["dual-boot", "..."],
"dual_boot": {
  // The partitions a switch writes, by their by-name label. A name is enough;
  // "size" makes both sides refuse a partition of any other size, and
  // "fallback" names the raw node for a Linux that has neither
  // /dev/disk/by-partlabel nor /dev/block/by-name.
  "partitions": ["boot"],
  "kernel_partition": "boot",          // written first; default "boot", else the first
  "linux_root": "linuxroot",           // the partition Linux's root filesystem is on
  "linux_root_fs": "ext4",             // default ext4
  "android_devices": ["gts9uwifi"],    // getprop ro.product.device on Android
  "android_data": "userdata",          // optional: for the storage bar on Linux
  "sets_dir": "/var/lib/galaxy-companion/boot-sets",          // optional
  "backups_dir": "/var/lib/galaxy-companion/boot-sets-backups", // optional
  "noask_rule": "/etc/polkit-1/rules.d/49-galaxy-companion-boot-switch.rules" // optional
}
```

To find the right partitions:

1. **List the boot chain.** On Android, `ls -l /dev/block/by-name/`. Candidates
   are `boot`, `init_boot`, `vendor_boot`, `dtbo`, `recovery` (never needed)
   and `vbmeta*` (never allowed).
2. **Hash them under each system.** Under Android and again under Linux, run
   `sha256sum /dev/block/by-name/<name>` for each candidate. List exactly the
   partitions whose hashes differ, kernel first. Leave out any partition that
   is the same under both systems. The first time, the app cannot tell such a
   partition from a half-finished switch, so it would refuse to save Android.
3. **Check `vbmeta`.** Android has to start with the `vbmeta` Linux needs. If
   it does not, this device cannot use this kind of dual boot.
4. **Check Linux's root.** Use its partition label as `linux_root`. It must not
   be `userdata`.
5. **Try it on the device.**
   - Install the package with the new profile, or put the profile in
     `/etc/galaxy-companion/devices/`.
   - Restart Linux. Then `ls <sets_dir>/linux` should list the images.
   - Build the app (below), install it on Android and open it. The console
     button shows what it saved and why.

Then run `ci/run-tests.sh` and `ci/android/build.sh`. The profile tests check
that every profile with `dual-boot` has partitions, `linux_root` and
`android_devices`. The app's tests check that it parses every shipped profile.

## Building and updating the Android app

```sh
ci/android/build.sh      # Docker: JDK 17, Android SDK 35, Gradle 8.10; debug APK + tests
adb install -r android/dualboot/app/build/outputs/apk/debug/app-debug.apk
```

The build copies the device profiles into the APK, so rebuild after changing
one. The app carries Galaxy Companion's version (2.3.0 is versionCode 20300)
and is released with it.

**Updates.** The app's *Updates* section looks for the newest release of
this repository. A release carries `galaxy-companion-dualboot_<version>.apk`
next to the `.deb`, and both are listed in its `SHA256SUMS`. *Download and
install* only hands the APK to Android's installer after these checks pass:
- the hash matches `SHA256SUMS`;
- it is this app's package with a higher version;
- it is signed with the same key as the installed app.

Android then asks for confirmation, as for any update. With *Check every
week* on, a background job notifies once per new version. While the
repository is private, GitHub answers no one, so there is nothing to find.

**Signing.** Android only installs an update signed like the installed app,
so every published APK is signed with one release key. The key is kept out of
the repository and must be backed up: losing it means users have to uninstall
before installing a newer build. `DUALBOOT_SIGNING` names a properties file
next to the key:

```properties
storeFile=dualboot-release.p12
storePassword=…
keyAlias=dualboot
keyPassword=…
```

`DUALBOOT_SIGNING=…/dualboot-release.properties scripts/publish-release.sh`
does the whole release:
1. runs both test suites;
2. builds the `.deb` and the signed APK;
3. refuses an APK not signed with that key;
4. writes `SHA256SUMS`;
5. creates the GitHub release.

Debug builds are signed with the build machine's debug key. A debug build
does not update over a release build, or the other way round, without
uninstalling first. The app id is `io.github.agcarbajo.galaxycompanion.dualboot`.
On the Tab it replaces the port's older `com.gts9u.bootswitcher`, which can be
uninstalled.

## When something goes wrong

- **"Unknown system"**: the boot partitions hold images that are in no set.
  - On Linux this is usually a new kernel: restart Linux.
  - On Android, the app's console says why it did not save them.
- **The app does not save Android:**
  - "not the running kernel": the boot partition holds someone else's
    kernel, for example after flashing Linux's images by hand.
  - "lz4-compressed": install Magisk, so `magiskboot` can unpack the kernel.
- **A switch stopped**: do not restart. Run it again, or switch back to the
  system you are on.
- **The device does not start**: the recovery partition is never written, so
  recovery still starts. From there, restore the boot images of either system.
  The saved sets are plain files on Linux's root partition.
