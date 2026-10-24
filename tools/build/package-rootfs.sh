#!/usr/bin/env bash
# Invoked only by package-rootfs.py inside its private Linux mount namespace.
set -euo pipefail
root="$(realpath "${1:?rootfs directory required}")"
[[ "$root" == */package-rootfs-*/rootfs && "$root" != /mnt/* ]] || {
    echo 'Expected a disposable Linux package rootfs.' >&2; exit 2;
}
# Distribution archives deliberately omit volatile directories. dpkg-deb
# needs a writable /tmp before debootstrap can configure the base system.
mkdir -p "$root/proc" "$root/sys" "$root/dev" "$root/run" "$root/tmp" "$root/var/tmp"
chmod 1777 "$root/tmp" "$root/var/tmp"
# Give the chroot its own visible root mount. libalpm resolves package/cache
# paths against mountinfo; the runner's enclosing mount lies outside chroot.
mount --bind "$root" "$root"
mount_virtual_filesystems() {
    mount -t proc proc "$root/proc"
    mount --rbind /dev "$root/dev"
    mount --make-rslave "$root/dev"
    mount --rbind /sys "$root/sys"
    mount --make-rslave "$root/sys"
}
mount_virtual_filesystems
export DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8
if [[ -x "$root/debootstrap/debootstrap" ]]; then
    if ! chroot "$root" /debootstrap/debootstrap --second-stage; then
        cat "$root/debootstrap/debootstrap.log" >&2
        exit 1
    fi
    # debootstrap's exit cleanup unmounts its proc/sys/dev submounts. Package
    # maintainer scripts run in the next stage and need a live procfs again.
    mount_virtual_filesystems
fi
for attempt in 1 2 3; do
    set +e
    chroot "$root" /bin/sh /usr/lib/arlinux/guest/build-desktop.sh
    result=$?
    set -e
    if [[ "$result" == 0 ]]; then
        exit 0
    fi
    # The package recipe explicitly restarts once after replacing glibc.
    [[ "$result" == 75 ]] || exit "$result"
done
echo 'Desktop package preparation did not converge.' >&2
exit 2
