#!/bin/bash
# Build the Android Dualboot app and run its unit tests in Docker.
#   ci/android/build.sh                      debug APK + tests
#   ci/android/build.sh assembleRelease      release APK, signed when
#     DUALBOOT_SIGNING names the signing properties file (see docs/dual-boot.md)
# Output: android/dualboot/app/build/outputs/apk/<debug|release>/
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
image=galaxy-companion-android
docker build -q -t "$image" "$repo/ci/android" >/dev/null
signing=()
if [ -n "${DUALBOOT_SIGNING:-}" ]; then
	dir=$(cd "$(dirname "$DUALBOOT_SIGNING")" && pwd)
	signing=(-v "$dir":/signing:ro -e DUALBOOT_SIGNING="/signing/$(basename "$DUALBOOT_SIGNING")")
fi
tasks=("$@")
[ ${#tasks[@]} -gt 0 ] || tasks=(assembleDebug)
docker run --rm -v "$repo":/src -v galaxy-companion-gradle:/root/.gradle ${signing[@]+"${signing[@]}"} \
	-w /src/android/dualboot "$image" \
	gradle --no-daemon --console=plain "${tasks[@]}" testDebugUnitTest
