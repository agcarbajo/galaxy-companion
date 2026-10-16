#!/bin/bash
# Run every scripts/test-*.py and build the package inside Ubuntu 24.04 with
# GTK 4 and libadwaita, headless.  Works from any host with Docker.
#   ci/run-tests.sh            all tests + package build
#   ci/run-tests.sh <test.py>  one test
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
image=galaxy-companion-ci
docker build -q -t "$image" "$repo/ci" >/dev/null
docker run --rm -v "$repo":/src:ro -e ONLY="${1-}" "$image" bash -c '
set -u
cp -a /src /w && cd /w
mkdir -p /tmp/schemas
cp packaging/galaxy-companion/usr/share/glib-2.0/schemas/*.gschema.xml /tmp/schemas/
glib-compile-schemas /tmp/schemas
export GSETTINGS_SCHEMA_DIR=/tmp/schemas GSETTINGS_BACKEND=memory
pass=0; fail=0
for t in ${ONLY:-scripts/test-*.py}; do
	if out=$(timeout 300 xvfb-run -a dbus-run-session -- python3 "$t" 2>&1); then
		pass=$((pass + 1)); echo "ok   $t"
	else
		fail=$((fail + 1)); echo "FAIL $t"; echo "$out" | tail -15 | sed "s/^/     /"
	fi
done
if [ -z "$ONLY" ]; then
	if UBUNTU_WORKDIR=/tmp/build bash scripts/build-companion-package.sh >/tmp/build.log 2>&1; then
		pass=$((pass + 1)); echo "ok   package build"
	else
		fail=$((fail + 1)); echo "FAIL package build"; tail -15 /tmp/build.log | sed "s/^/     /"
	fi
fi
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]'
