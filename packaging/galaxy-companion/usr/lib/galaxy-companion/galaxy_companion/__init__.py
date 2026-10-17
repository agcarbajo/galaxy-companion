# SPDX-License-Identifier: MIT

APP_ID = "io.github.agcarbajo.GalaxyCompanion"
# Galaxy Companion restarted its numbering at 0.9.0 when it became its own
# project; 1.0.0 is the first official release.  The Debian version carries
# epoch 1 so that apt and the self-updater rank these above the 1.x Tab
# Companion and 2.x pre-rename packages already installed on some devices.
VERSION = "0.9.0"
EPOCH = "1"
DEBIAN_VERSION = EPOCH + ":" + VERSION
