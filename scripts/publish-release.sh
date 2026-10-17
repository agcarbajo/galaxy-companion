#!/bin/bash
# Build the package and publish it as a GitHub release of this repository,
# with the SHA256SUMS that Galaxy Companion's own updater requires.
#   scripts/publish-release.sh            release the version in DEBIAN/control
#   GH=../gh-agc.sh scripts/publish-release.sh   use another gh wrapper
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
gh=${GH:-gh}
version=$(awk '/^Version:/ {print $2}' "$repo/packaging/galaxy-companion/DEBIAN/control")
code=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$repo/packaging/galaxy-companion/usr/lib/galaxy-companion/galaxy_companion/__init__.py")
[ "$version" = "$code" ] || { echo "DEBIAN/control says $version, __init__.py says $code" >&2; exit 1; }
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
deb=galaxy-companion_${version}_all.deb
# The package is built in the CI image, so it is the same on any host.
"$repo/ci/run-tests.sh"
docker run --rm -v "$repo":/src:ro -v "$out":/out galaxy-companion-ci bash -c \
	'cp -a /src /w && cd /w && UBUNTU_WORKDIR=/tmp/b DEB_OUT_DIR=/out bash scripts/build-companion-package.sh >/dev/null'
(cd "$out" && sha256sum "$deb" > SHA256SUMS)
notes=$(python3 - "$repo/packaging/galaxy-companion/usr/share/metainfo/io.github.agcarbajo.GalaxyCompanion.metainfo.xml" "$version" <<'PY'
import sys, xml.etree.ElementTree as ET
for release in ET.parse(sys.argv[1]).iter("release"):
    if release.get("version") == sys.argv[2]:
        print(" ".join(p.text or "" for p in release.iter("p")))
PY
)
"$gh" release create "v$version" "$out/$deb" "$out/SHA256SUMS" \
	--repo agcarbajo/galaxy-companion --title "Galaxy Companion $version" --notes "$notes"
