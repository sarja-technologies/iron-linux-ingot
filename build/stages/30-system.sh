# shellcheck shell=bash
# Stage 30: turn the base rootfs into the Ingot system (kernel, firmware,
# desktop, drivers, live/installer tooling) from Ubuntu + the local Ingot repo.

LOCAL_REPO_MNT="/var/lib/ingot-build-repo"

# Packages purged after install: telemetry, crash reporting, snap integration
# and first-run wizards that Ingot replaces.
INGOT_PURGE="apport apport-gtk apport-symptoms whoopsie popularity-contest ubuntu-report \
 gnome-initial-setup snapd ubuntu-advantage-tools ubuntu-pro-client update-notifier"

stage_system() {
    [[ -x "${ROOTFS}/usr/bin/apt-get" ]] || die "rootfs not bootstrapped; run the bootstrap stage first"
    local repo="${INGOT_WORKDIR}/repo"
    [[ -s "${repo}/dists/${INGOT_CODENAME}/InRelease" ]] || die "local Ingot repo missing; run the packages stage"

    chroot_mount
    _mount --bind "${repo}" "${ROOTFS}${LOCAL_REPO_MNT}"
    install -Dm644 "${repo}/iron-archive-dev.gpg" "${ROOTFS}/usr/share/keyrings/iron-archive-dev.gpg"
    cat > "${ROOTFS}/etc/apt/sources.list.d/ingot-build-local.sources" <<EOF
Types: deb
URIs: file:${LOCAL_REPO_MNT}
Suites: ${INGOT_CODENAME}
Components: main
Signed-By: /usr/share/keyrings/iron-archive-dev.gpg
EOF

    configure_base_identity
    apt_chroot update
    apt_chroot dist-upgrade

    log "installing Ingot base policy (snap block, Mozilla repo) first"
    apt_chroot install iron-base-files
    apt_chroot update

    local meta="ingot-desktop"
    [[ "${PROFILE}" == lite ]] && meta="ingot-desktop-lite"
    local pkgs
    mapfile -t pkgs < <(read_list "${INGOT_ROOT}/build/config/packages/"*.list)
    log "installing ${KERNEL_PKG}, ${meta} and ${#pkgs[@]} image packages"
    apt_chroot install "${KERNEL_PKG}" "${meta}" "${pkgs[@]}"

    # Optional components present in the repo (e.g. Gnotch): installed, not enabled.
    if in_chroot apt-cache show gnotch >/dev/null 2>&1; then
        apt_chroot install gnotch || warn "gnotch failed to install; continuing without it"
    fi

    log "purging unwanted defaults"
    local present=()
    for p in ${INGOT_PURGE}; do
        # shellcheck disable=SC2016 # dpkg-query format string, not a shell expansion
        in_chroot dpkg-query -W -f='${Status}' "${p}" 2>/dev/null | grep -q "ok installed" && present+=("${p}")
    done
    [[ ${#present[@]} -gt 0 ]] && apt_chroot purge "${present[@]}"
    apt_chroot autoremove --purge

    configure_system

    # Remove build-only APT source/key; installed systems keep Ubuntu + Mozilla sources.
    rm -f "${ROOTFS}/etc/apt/sources.list.d/ingot-build-local.sources" \
          "${ROOTFS}/usr/share/keyrings/iron-archive-dev.gpg"
    if [[ -n "${INGOT_APT_URL:-}" ]]; then
        install_published_iron_source
    fi
    apt_chroot update || true
    in_chroot apt-get clean
    rm -rf "${ROOTFS}/var/lib/apt/lists/"*_dists_* 2>/dev/null || true

    # shellcheck disable=SC2016 # dpkg-query format string
    in_chroot dpkg-query -W -f='${Package}\t${Version}\n' > "${WORK}/manifest.tsv"
    cp "${WORK}/manifest.tsv" "${OUTDIR}/iron-ingot-${INGOT_VERSION}-${ARCH}-${PROFILE}.manifest"
    log "installed $(wc -l < "${WORK}/manifest.tsv") packages; $(du -sh --exclude=proc --exclude=sys "${ROOTFS}" 2>/dev/null | cut -f1) rootfs"
    chroot_umount
}

configure_base_identity() {
    echo "iron-ingot" > "${ROOTFS}/etc/hostname"
    cat > "${ROOTFS}/etc/hosts" <<'EOF'
127.0.0.1   localhost
127.0.1.1   iron-ingot
::1         localhost ip6-localhost ip6-loopback
ff02::1     ip6-allnodes
ff02::2     ip6-allrouters
EOF
    in_chroot ln -sf /usr/share/zoneinfo/Etc/UTC /etc/localtime
    sed -i 's/^# *en_US.UTF-8/en_US.UTF-8/' "${ROOTFS}/etc/locale.gen" 2>/dev/null || true
    grep -q '^en_US.UTF-8' "${ROOTFS}/etc/locale.gen" 2>/dev/null || echo "en_US.UTF-8 UTF-8" >> "${ROOTFS}/etc/locale.gen"
    in_chroot locale-gen
    echo 'LANG=en_US.UTF-8' > "${ROOTFS}/etc/default/locale"
}

configure_system() {
    log "configuring system services and live defaults"
    # NetworkManager manages every device (no netplan on Ingot).
    mkdir -p "${ROOTFS}/etc/NetworkManager/conf.d"
    : > "${ROOTFS}/etc/NetworkManager/conf.d/10-globally-managed-devices.conf"
    in_chroot systemctl set-default graphical.target
    in_chroot systemctl enable NetworkManager.service gdm3.service iron-hwprofile.service 2>/dev/null || \
        in_chroot systemctl enable NetworkManager.service gdm.service iron-hwprofile.service
    # GDM: Wayland only (XWayland is still available to apps).
    if [[ -f "${ROOTFS}/etc/gdm3/custom.conf" ]]; then
        sed -i 's/^#\?WaylandEnable=.*/WaylandEnable=true/' "${ROOTFS}/etc/gdm3/custom.conf"
    fi
    # Live session identity for casper.
    cat > "${ROOTFS}/etc/casper.conf" <<'EOF'
# Iron Linux Ingot live session
export USERNAME="iron"
export USERFULLNAME="Iron Live Session"
export HOST="iron-ingot"
export BUILD_SYSTEM="Ubuntu"
export FLAVOUR="Iron"
EOF
    # Each installed system must generate its own machine-id.
    : > "${ROOTFS}/etc/machine-id"
    rm -f "${ROOTFS}/var/lib/dbus/machine-id"
    in_chroot update-initramfs -u -k all
}

install_published_iron_source() {
    # Same code path as on an installed system: the packaged keyring is the
    # only key trusted for the source, and the pin limits it to Ingot packages.
    in_chroot iron-update set-source "${INGOT_APT_URL}" --suite "${INGOT_CODENAME}"
}
