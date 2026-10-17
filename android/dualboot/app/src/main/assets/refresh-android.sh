# Saves the live boot partitions as Android's set, on Linux's root filesystem.
# Run by BootMaintenance under the same lock as partition switching, after it
# has checked that the kernel is the running Android's.  Only files are
# written here: no dd destination is a block device.
#
# Assigned by the caller: MOUNTPOINT (Linux's root, mounted read-only), BASE
# and BACKUP (the sets and backups directories inside it), SET_ID,
# SYSTEM_NAME, EXPECTED ("<sha256>  <part>.img" lines), PARTS ("name:bytes
# ...", kernel first) and CHANGED (1 to copy the images, 0 to fix the name).
set -eu
case "$SET_ID" in ''|*[!a-zA-Z0-9_-]*) exit 1;; esac
if grep " $MOUNTPOINT " /proc/mounts | grep -q noload; then
    echo "Android: Linux's filesystem needs recovery; nothing saved."
    exit 1
fi
old=$BASE/$SET_ID
previous=$BACKUP/$SET_ID.previous
stage=$BACKUP/$SET_ID.pending
writable=0
cleanup() {
    result=$?
    set +e
    if [ "$writable" = 1 ] && [ ! -d "$old" ] && [ -d "$previous" ]; then mv "$previous" "$old"; fi
    rm -rf "$stage"
    sync
    if [ "$writable" = 1 ]; then mount -o remount,ro "$MOUNTPOINT" || result=1; fi
    exit "$result"
}
trap cleanup EXIT
mount -o remount,rw "$MOUNTPOINT"
writable=1
mkdir -p "$BASE" "$BACKUP"
# Recover a power loss between the two directory renames.
if [ ! -d "$old" ] && [ -d "$previous" ]; then mv "$previous" "$old"; fi
if [ "$CHANGED" = 1 ]; then
    rm -rf "$stage"
    mkdir "$stage"
    for spec in $PARTS; do
        part=${spec%%:*}
        bytes=${spec#*:}
        test "$(blockdev --getsize64 /dev/block/by-name/$part)" = "$bytes"
        dd if=/dev/block/by-name/$part of="$stage/$part.img" bs=4M 2>/dev/null
        test "$(stat -c %s "$stage/$part.img")" = "$bytes"
    done
    printf '%s\n' "$EXPECTED" > "$stage/expected"
    (cd "$stage"; sha256sum -c expected >/dev/null)
    # A concurrent OTA or root tool must not turn the snapshot into a mixed set.
    for spec in $PARTS; do
        part=${spec%%:*}
        test "$(sha256sum /dev/block/by-name/$part | cut -d ' ' -f1)" = "$(sha256sum "$stage/$part.img" | cut -d ' ' -f1)"
    done
    rm "$stage/expected"
    printf '%s\n' "$SYSTEM_NAME" > "$stage/name.txt"
    printf 'android\n' > "$stage/kind"
    sync
    rm -rf "$previous"
    if [ -d "$old" ]; then mv "$old" "$previous"; fi
    mv "$stage" "$old"
    sync
    echo "Android: $SET_ID saved and verified; the previous copy is kept."
else
    printf '%s\n' "$SYSTEM_NAME" > "$old/name.txt.new"
    mv "$old/name.txt.new" "$old/name.txt"
    printf 'android\n' > "$old/kind"
    echo "Android: $SET_ID name corrected."
fi
