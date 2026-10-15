# shellcheck shell=bash
# Stage 10: minimal Ubuntu base via debootstrap (cached as a tarball per arch).
# shellcheck disable=SC2153 # MIRROR is exported by arch_setup in lib/common.sh

stage_bootstrap() {
    local tarball="${CACHE}/debootstrap-${INGOT_UBUNTU_SUITE}.tar"
    # shellcheck disable=SC2054 # commas are inside option values, not separators
    local opts=(--arch="${ARCH}" --variant=minbase
                --components="${INGOT_COMPONENTS// /,}"
                --include=ca-certificates,gnupg,apt-utils,locales,systemd-sysv,dbus)
    if [[ -n "${QEMU_STATIC}" ]]; then
        # The host binfmt handler (flag F) runs foreign binaries transparently.
        grep -q enabled /proc/sys/fs/binfmt_misc/qemu-aarch64 2>/dev/null \
            || die "qemu-aarch64 binfmt handler not registered (apt install qemu-user-binfmt)"
    fi

    if [[ -d "${ROOTFS}" ]]; then
        log "removing previous rootfs"
        chroot_umount
        safe_rm_tree "${ROOTFS}"
    fi

    if [[ ! -s "${tarball}" ]]; then
        log "downloading base packages (${INGOT_UBUNTU_SUITE}, ${ARCH}) -> ${tarball}"
        debootstrap "${opts[@]}" --make-tarball="${tarball}" \
            "${INGOT_UBUNTU_SUITE}" "${WORK}/tarball-tmp" "${MIRROR}"
        rm -rf --one-file-system "${WORK}/tarball-tmp"
    fi

    log "debootstrap ${INGOT_UBUNTU_SUITE} ${ARCH} into ${ROOTFS}"
    debootstrap "${opts[@]}" --unpack-tarball="${tarball}" \
        "${INGOT_UBUNTU_SUITE}" "${ROOTFS}" "${MIRROR}"

    write_apt_sources
    log "bootstrap complete"
}

write_apt_sources() {
    local mirror="${MIRROR}" security
    if [[ "${ARCH}" == amd64 ]]; then
        security="http://security.ubuntu.com/ubuntu"
    else
        security="http://ports.ubuntu.com/ubuntu-ports"
    fi
    if [[ -n "${INGOT_SNAPSHOT}" ]]; then
        mirror="https://snapshot.ubuntu.com/${MIRROR##*/}/${INGOT_SNAPSHOT}"
        security="${mirror}"
    fi
    rm -f "${ROOTFS}/etc/apt/sources.list"
    mkdir -p "${ROOTFS}/etc/apt/sources.list.d"
    cat > "${ROOTFS}/etc/apt/sources.list.d/ubuntu.sources" <<EOF
Types: deb
URIs: ${mirror}
Suites: ${INGOT_UBUNTU_SUITE} ${INGOT_UBUNTU_SUITE}-updates ${INGOT_UBUNTU_SUITE}-backports
Components: ${INGOT_COMPONENTS}
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: ${security}
Suites: ${INGOT_UBUNTU_SUITE}-security
Components: ${INGOT_COMPONENTS}
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
}
