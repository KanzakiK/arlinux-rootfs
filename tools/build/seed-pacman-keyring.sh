#!/usr/bin/env bash
set -euo pipefail
root=${1:?rootfs required}
shift
destination=$root/etc/pacman.d/gnupg
# Agent sockets must not inherit the deeply nested build-cache path. Only the
# public keyring and trust database belong in the image, not host agent state.
home=$(mktemp -d /tmp/arlinux-keyring.XXXXXXXX)
cleanup() {
    gpgconf --homedir "$home" --kill all || true
    rm -rf -- "$home"
}
trap cleanup EXIT
mkdir -p "$destination"
chmod 700 "$destination"
keyrings=$root/usr/share/pacman/keyrings
keys=() trusted=()
for name in "$@"; do
    keys+=("$keyrings/$name.gpg")
    trusted+=("$keyrings/$name-trusted")
done
# GnuPG's root-owned trust database cannot be created on Android, where the
# extracted tree is owned by the app UID. Generate it with the signed seed.
gpg --homedir "$home" --no-default-keyring --keyring "$home/pubring.gpg" \
    --batch --quiet --import "${keys[@]}"
awk -F: 'NF >= 2 && $1 ~ /^[[:xdigit:]]{40}$/ { print $1 ":6:" }' \
    "${trusted[@]}" |
    gpg --homedir "$home" --batch --quiet --import-ownertrust
gpg --homedir "$home" --batch --quiet --check-trustdb
install -m 644 "$home/pubring.gpg" "$home/trustdb.gpg" "$destination/"
touch "$destination/secring.gpg" "$destination/arlinux-populated"
chmod 600 "$destination/secring.gpg"
