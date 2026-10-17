#!/bin/bash
# Build the package and the Android Dualboot app and publish both as a GitHub
# release of this repository, with the SHA256SUMS both updaters require.
#   DUALBOOT_SIGNING=../keys/dualboot-release.properties scripts/publish-release.sh
#   GH=../gh-agc.sh ...   use another gh wrapper
#   PRERELEASE=1 ...      mark it as a pre-release: the updaters, which ask
#                         GitHub for the latest release, do not offer it
# The APK must be signed with the release key every time: Android only
# installs an update signed like the app already installed.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
gh=${GH:-gh}
# The Debian version carries epoch 1 (see __init__.py); tags, file names and
# release notes use the version without it.
version=$(awk '/^Version:/ {print $2}' "$repo/packaging/galaxy-companion/DEBIAN/control")
version=${version#*:}
code=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$repo/packaging/galaxy-companion/usr/lib/galaxy-companion/galaxy_companion/__init__.py")
[ "$version" = "$code" ] || { echo "DEBIAN/control says $version, __init__.py says $code" >&2; exit 1; }
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
deb=galaxy-companion_${version}_all.deb
apk=galaxy-companion-dualboot_${version}.apk
[ -f "${DUALBOOT_SIGNING:-}" ] || { echo "Set DUALBOOT_SIGNING to the release signing properties file" >&2; exit 1; }
# The package is built in the CI image, so it is the same on any host.
"$repo/ci/run-tests.sh"
docker run --rm -v "$repo":/src:ro -v "$out":/out galaxy-companion-ci bash -c \
	'cp -a /src /w && cd /w && UBUNTU_WORKDIR=/tmp/b DEB_OUT_DIR=/out bash scripts/build-companion-package.sh >/dev/null'
"$repo/ci/android/build.sh" assembleRelease
cp "$repo/android/dualboot/app/build/outputs/apk/release/app-release.apk" "$out/$apk"
# An unsigned or debug-signed APK would never install over a released one.
# (Read whole first: grep -q closing the pipe early would fail it under pipefail.)
certs=$(docker run --rm -v "$out":/out galaxy-companion-android \
	/opt/android-sdk/build-tools/35.0.0/apksigner verify --print-certs "/out/$apk" 2>/dev/null) || true
grep -q 'CN=Galaxy Companion Dualboot' <<<"$certs" \
	|| { echo "$apk is not signed with the release key" >&2; exit 1; }
(cd "$out" && sha256sum "$deb" "$apk" > SHA256SUMS)
notes=$(python3 - "$repo/packaging/galaxy-companion/usr/share/metainfo/io.github.agcarbajo.GalaxyCompanion.metainfo.xml" "$version" <<'PY'
import sys, xml.etree.ElementTree as ET
for release in ET.parse(sys.argv[1]).iter("release"):
    if release.get("version") == sys.argv[2]:
        print(" ".join(p.text or "" for p in release.iter("p")))
PY
)
"$gh" release create "v$version" "$out/$deb" "$out/$apk" "$out/SHA256SUMS" \
	--repo agcarbajo/galaxy-companion --title "Galaxy Companion $version" --notes "$notes" \
	${PRERELEASE:+--prerelease}
