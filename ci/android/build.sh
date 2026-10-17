#!/bin/bash
# Build the Android Dualboot app and run its unit tests in Docker.
#   ci/android/build.sh        -> android/dualboot/app/build/outputs/apk/debug/*.apk
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
image=galaxy-companion-android
docker build -q -t "$image" "$repo/ci/android" >/dev/null
docker run --rm -v "$repo":/src -v galaxy-companion-gradle:/root/.gradle \
	-w /src/android/dualboot "$image" \
	gradle --no-daemon --console=plain assembleDebug testDebugUnitTest "$@"
