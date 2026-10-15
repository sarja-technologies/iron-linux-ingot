# shellcheck shell=bash
# Iron Linux Ingot - shared build helpers. Sourced by build/ingot-build and stages.

set -euo pipefail

INGOT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export INGOT_ROOT

# shellcheck source=build/config/common.conf
. "${INGOT_ROOT}/build/config/common.conf"

log()  { printf '\033[1;34m[ingot %s]\033[0m %s\n' "${ARCH:-?}" "$*" >&2; }
warn() { printf '\033[1;33m[ingot %s] WARN:\033[0m %s\n' "${ARCH:-?}" "$*" >&2; }
die()  { printf '\033[1;31m[ingot %s] ERROR:\033[0m %s\n' "${ARCH:-?}" "$*" >&2; exit 1; }

require_root() { [[ ${EUID} -eq 0 ]] || die "must run as root (sudo build/ingot-build ...)"; }

# Per-arch settings -------------------------------------------------------
arch_setup() {
    case "${ARCH}" in
        amd64)
            MIRROR="${INGOT_MIRROR_AMD64}"
            KERNEL_PKG="linux-generic-hwe-${INGOT_UBUNTU_VERSION}"
            GRUB_EFI_TARGET="x86_64-efi"
            GRUB_EFI_PKGS="grub-efi-amd64-bin grub-efi-amd64-signed shim-signed grub-pc-bin"
            EFI_BOOT_NAME="BOOTX64.EFI"
            QEMU_STATIC=""
            ;;
        arm64)
            MIRROR="${INGOT_MIRROR_ARM64}"
            KERNEL_PKG="linux-generic-hwe-${INGOT_UBUNTU_VERSION}"
            GRUB_EFI_TARGET="arm64-efi"
            GRUB_EFI_PKGS="grub-efi-arm64-bin grub-efi-arm64-signed shim-signed"
            EFI_BOOT_NAME="BOOTAA64.EFI"
            QEMU_STATIC="/usr/bin/qemu-aarch64"
            ;;
        *) die "unsupported ARCH '${ARCH}' (expected amd64 or arm64)" ;;
    esac
    WORK="${INGOT_WORKDIR}/${ARCH}-${PROFILE}"
    ROOTFS="${WORK}/rootfs"
    CACHE="${INGOT_WORKDIR}/cache/${ARCH}"
    OUTDIR="${INGOT_ROOT}/out"
    export MIRROR KERNEL_PKG GRUB_EFI_TARGET GRUB_EFI_PKGS EFI_BOOT_NAME QEMU_STATIC WORK ROOTFS CACHE OUTDIR
    mkdir -p "${WORK}" "${CACHE}/archives" "${OUTDIR}"
}

# Chroot mounts -----------------------------------------------------------
# Every mount we create is recorded so cleanup only ever touches our own mounts.
_INGOT_MOUNTS=()

_mount() { # _mount <args...> <target>
    local target="${*: -1}"
    mkdir -p "${target}"
    mount "$@"
    _INGOT_MOUNTS+=("${target}")
}

chroot_mount() {
    [[ -d "${ROOTFS}" ]] || die "rootfs missing: ${ROOTFS}"
    findmnt -rn "${ROOTFS}/proc" >/dev/null && return 0
    _mount -t proc proc "${ROOTFS}/proc"
    _mount -t sysfs sysfs "${ROOTFS}/sys"
    _mount --bind /dev "${ROOTFS}/dev"
    _mount -t devpts devpts -o gid=5,mode=620,newinstance,ptmxmode=666 "${ROOTFS}/dev/pts"
    _mount -t tmpfs tmpfs "${ROOTFS}/run"
    _mount --bind "${CACHE}/archives" "${ROOTFS}/var/cache/apt/archives"
    # Do not start services inside the chroot.
    printf '#!/bin/sh\nexit 101\n' > "${ROOTFS}/usr/sbin/policy-rc.d"
    chmod 755 "${ROOTFS}/usr/sbin/policy-rc.d"
    cp -L /etc/resolv.conf "${ROOTFS}/etc/resolv.conf.ingot-build" 2>/dev/null || true
    if [[ -L "${ROOTFS}/etc/resolv.conf" || ! -s "${ROOTFS}/etc/resolv.conf" ]]; then
        mv -f "${ROOTFS}/etc/resolv.conf" "${ROOTFS}/etc/resolv.conf.ingot-orig" 2>/dev/null || true
        cp -L /etc/resolv.conf "${ROOTFS}/etc/resolv.conf"
    fi
}

chroot_umount() {
    local i
    for (( i=${#_INGOT_MOUNTS[@]}-1; i>=0; i-- )); do
        umount "${_INGOT_MOUNTS[$i]}" 2>/dev/null || umount -l "${_INGOT_MOUNTS[$i]}" 2>/dev/null || true
    done
    _INGOT_MOUNTS=()
    # Belt and braces: anything still mounted below ROOTFS (e.g. from an aborted run).
    if [[ -n "${ROOTFS:-}" && -d "${ROOTFS}" ]]; then
        { findmnt -rn -o TARGET | grep -F "${ROOTFS}/" || true; } | sort -r | while read -r m; do
            umount -l "${m}" 2>/dev/null || true
        done
    fi
    if [[ -n "${ROOTFS:-}" && -d "${ROOTFS}/etc" ]]; then
        rm -f "${ROOTFS}/usr/sbin/policy-rc.d" "${ROOTFS}/etc/resolv.conf.ingot-build"
        if [[ -e "${ROOTFS}/etc/resolv.conf.ingot-orig" || -L "${ROOTFS}/etc/resolv.conf.ingot-orig" ]]; then
            mv -f "${ROOTFS}/etc/resolv.conf.ingot-orig" "${ROOTFS}/etc/resolv.conf"
        fi
    fi
}

in_chroot() {
    LC_ALL=C.UTF-8 DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true \
        chroot "${ROOTFS}" /usr/bin/env -i \
        PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root LC_ALL=C.UTF-8 \
        DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true \
        "$@"
}

apt_chroot() {
    in_chroot apt-get -y -q -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold "$@"
}

# Refuse to delete anything that still has mounts underneath it.
safe_rm_tree() {
    local d="$1"
    [[ -n "${d}" && "${d}" == "${INGOT_WORKDIR}"/* ]] || die "refusing to remove '${d}' (outside workdir)"
    if findmnt -rn -o TARGET | grep -qF "${d}/"; then
        die "refusing to remove '${d}': active mounts below it"
    fi
    rm -rf --one-file-system "${d}"
}

# Read a package list, dropping comments/blank lines; supports [amd64]/[arm64] suffix filters
# and {lite}/{full} profile filters.
read_list() {
    local f line pkg tags
    for f in "$@"; do
        [[ -f "${f}" ]] || continue
        while IFS= read -r line || [[ -n "${line}" ]]; do
            line="${line%%#*}"; line="$(echo "${line}" | xargs)"
            [[ -z "${line}" ]] && continue
            pkg="${line%% *}"; tags=" ${line#"${pkg}"} "
            if [[ "${tags}" == *"["*"]"* && "${tags}" != *"[${ARCH}]"* ]]; then continue; fi
            if [[ "${tags}" == *"{"*"}"* && "${tags}" != *"{${PROFILE}}"* ]]; then continue; fi
            echo "${pkg}"
        done < "${f}"
    done
}
