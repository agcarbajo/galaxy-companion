#!/bin/bash
# Build the architecture-independent Galaxy Companion Debian package.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
base=${UBUNTU_WORKDIR:-/root/ubuntu-gts9u}
src=$repo/packaging/galaxy-companion
out=${DEB_OUT_DIR:-$base/out/packages}

version=$(awk '/^Version:/ {print $2}' "$src/DEBIAN/control")
# Debian file names leave the epoch out, as dpkg does.
upstream=${version#*:}
staging=$base/build/deb/galaxy-companion
deb=$out/galaxy-companion_${upstream}_all.deb

rm -rf -- "$staging"
mkdir -p "$staging" "$out"
cp -a "$src/." "$staging/"
find "$staging" -type f -name '*.pyc' -delete
find "$staging" -type d -name '__pycache__' -empty -delete

# Gio resources keep the illustration independent of the current directory.
resource_dir=$staging/usr/share/galaxy-companion
cat > "$resource_dir/io.github.agcarbajo.GalaxyCompanion.gresource.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<gresources>
  <gresource prefix="/io/github/agcarbajo/GalaxyCompanion/images">
    <file alias="spen-tip-left.svg">spen-tip-left.svg</file>
    <file alias="spen-tip-right.svg">spen-tip-right.svg</file>
  </gresource>
</gresources>
EOF
glib-compile-resources --sourcedir="$resource_dir" \
	--target="$resource_dir/io.github.agcarbajo.GalaxyCompanion.gresource" \
	"$resource_dir/io.github.agcarbajo.GalaxyCompanion.gresource.xml"
rm "$resource_dir/io.github.agcarbajo.GalaxyCompanion.gresource.xml" \
	"$resource_dir/spen-tip-left.svg" \
	"$resource_dir/spen-tip-right.svg"

# Load the resource before Python starts importing the UI.
sed -i '5i\from gi.repository import Gio\nGio.resources_register(Gio.Resource.load("/usr/share/galaxy-companion/io.github.agcarbajo.GalaxyCompanion.gresource"))' \
	"$staging/usr/bin/galaxy-companion"

glib-compile-schemas --strict "$staging/usr/share/glib-2.0/schemas"
desktop-file-validate "$staging/usr/share/applications/io.github.agcarbajo.GalaxyCompanion.desktop"
appstreamcli validate --no-net "$staging/usr/share/metainfo/io.github.agcarbajo.GalaxyCompanion.metainfo.xml"
python3 -m compileall -q "$staging/usr/lib/galaxy-companion"
# Validate syntax above, but let the target's Python build its own caches.
find "$staging/usr/lib/galaxy-companion" -type f -name '*.pyc' -delete
find "$staging/usr/lib/galaxy-companion" -type d -name '__pycache__' -empty -delete

chown -R root:root "$staging"
find "$staging" -type d -exec chmod 0755 {} +
find "$staging" -type f -exec chmod 0644 {} +
chmod 0755 "$staging/usr/bin/galaxy-companion" \
	"$staging/usr/bin/gts9u-update" \
	"$staging/DEBIAN/postinst" "$staging/DEBIAN/postrm"
# Everything in libexec is something polkit or the window runs, so mark the
# whole directory rather than a list: the boot helpers were missing from the
# list they were meant to be on, and shipped unexecutable because of it.
find "$staging/usr/libexec" -type f -exec chmod 0755 {} +
find "$staging" -exec touch -h -d '@0' {} +

dpkg-deb --root-owner-group --build "$staging" "$deb"
dpkg-deb --contents "$deb"
sha256sum "$deb"
