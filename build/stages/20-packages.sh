# shellcheck shell=bash
# Stage 20: build the Ingot .debs in a clean amd64 builder chroot and publish
# them into a local, signed APT repository (shared by every arch: all packages
# are Architecture: all).

REPO_DIR() { echo "${INGOT_WORKDIR}/repo"; }
KEY_DIR() { echo "${INGOT_WORKDIR}/keys"; }

ensure_signing_key() {
    local kd; kd="$(KEY_DIR)"
    if [[ ! -s "${kd}/archive.pub.gpg" ]]; then
        log "generating development archive signing key (kept in ${kd}, never committed)"
        install -d -m700 "${kd}"
        GNUPGHOME="${kd}" gpg --batch --quiet --pinentry-mode loopback --passphrase '' \
            --quick-gen-key "Iron Linux Ingot development archive (local builds)" ed25519 sign 2y
        GNUPGHOME="${kd}" gpg --batch --export > "${kd}/archive.pub.gpg"
    fi
}

stage_packages() {
    local builder="${INGOT_WORKDIR}/builder-amd64"
    local tarball="${INGOT_WORKDIR}/cache/amd64/debootstrap-${INGOT_UBUNTU_SUITE}.tar"
    local repo; repo="$(REPO_DIR)"
    local src_hash
    src_hash="$(cd "${INGOT_ROOT}" && { git ls-files -co --exclude-standard -z \
        | grep -zv '^build/' | sort -z | xargs -0 sha256sum; } | sha256sum | cut -c1-16)"
    if [[ -f "${repo}/.src-hash" && "$(cat "${repo}/.src-hash")" == "${src_hash}" && -z "${INGOT_FORCE_PACKAGES:-}" ]]; then
        log "packages up to date (${src_hash}); skipping (INGOT_FORCE_PACKAGES=1 to rebuild)"
        return 0
    fi
    [[ -s "${tarball}" ]] || die "amd64 base tarball missing; run: sudo build/ingot-build --arch amd64 bootstrap"

    # Builder chroot is always amd64 (native, fast) and reused between builds.
    local saved_rootfs="${ROOTFS}" saved_cache="${CACHE}" saved_arch="${ARCH}" saved_mirror="${MIRROR}"
    ROOTFS="${builder}"; CACHE="${INGOT_WORKDIR}/cache/amd64"; ARCH=amd64; MIRROR="${INGOT_MIRROR_AMD64}"
    if [[ ! -x "${builder}/usr/bin/dpkg-buildpackage" ]]; then
        log "creating package builder chroot"
        [[ -d "${builder}" ]] && { chroot_umount; safe_rm_tree "${builder}"; }
        debootstrap --arch=amd64 --variant=minbase --components="${INGOT_COMPONENTS// /,}" \
            --unpack-tarball="${tarball}" "${INGOT_UBUNTU_SUITE}" "${builder}" "${MIRROR}"
        write_apt_sources
        chroot_mount
        apt_chroot update
        apt_chroot install --no-install-recommends build-essential dpkg-dev debhelper fakeroot git
        chroot_umount
    fi

    log "syncing source tree into builder"
    rm -rf --one-file-system "${builder}/src"
    mkdir -p "${builder}/src/ingot"
    (cd "${INGOT_ROOT}" && git ls-files -co --exclude-standard -z | grep -zv '^build-area/' \
        | xargs -0 cp --parents -a -t "${builder}/src/ingot")

    # Unique, increasing version per build so apt upgrades existing systems/rootfs.
    sed -i "1s/(\([^)]*\))/(\1+b$(date -u +%Y%m%d%H%M%S))/" "${builder}/src/ingot/debian/changelog"
    head -n 1 "${builder}/src/ingot/debian/changelog" >&2

    chroot_mount
    apt_chroot update
    in_chroot sh -c 'cd /src/ingot && apt-get build-dep -y -q --no-install-recommends ./'
    log "dpkg-buildpackage"
    in_chroot sh -c 'cd /src/ingot && dpkg-buildpackage -b -us -uc' \
        > "${INGOT_WORKDIR}/packages-build.log" 2>&1 \
        || { tail -n 60 "${INGOT_WORKDIR}/packages-build.log" >&2; die "package build failed (see ${INGOT_WORKDIR}/packages-build.log)"; }
    chroot_umount
    ROOTFS="${saved_rootfs}"; CACHE="${saved_cache}"; ARCH="${saved_arch}"; MIRROR="${saved_mirror}"

    publish_repo "${builder}/src"
    echo "${src_hash}" > "${repo}/.src-hash"
}

publish_repo() {
    local debdir="$1" repo; repo="$(REPO_DIR)"
    ensure_signing_key
    log "publishing local APT repo ${repo}"
    rm -rf --one-file-system "${repo}"
    mkdir -p "${repo}/pool" "${repo}/dists/${INGOT_CODENAME}/main/binary-all"
    cp "${debdir}"/*.deb "${repo}/pool/"
    (
        cd "${repo}" || exit 1
        apt-ftparchive packages pool > "dists/${INGOT_CODENAME}/main/binary-all/Packages"
        gzip -9kf "dists/${INGOT_CODENAME}/main/binary-all/Packages"
        apt-ftparchive \
            -o APT::FTPArchive::Release::Origin="Iron Linux" \
            -o APT::FTPArchive::Release::Label="Iron Linux Ingot (local build)" \
            -o APT::FTPArchive::Release::Suite="${INGOT_CODENAME}" \
            -o APT::FTPArchive::Release::Codename="${INGOT_CODENAME}" \
            -o APT::FTPArchive::Release::Architectures="all amd64 arm64" \
            -o APT::FTPArchive::Release::Components="main" \
            release "dists/${INGOT_CODENAME}" > "dists/${INGOT_CODENAME}/Release"
        GNUPGHOME="$(KEY_DIR)" gpg --batch --yes --clearsign \
            -o "dists/${INGOT_CODENAME}/InRelease" "dists/${INGOT_CODENAME}/Release"
    )
    cp "$(KEY_DIR)/archive.pub.gpg" "${repo}/iron-archive-dev.gpg"
    find "${repo}/pool" -name '*.deb' -printf '    %f\n' | sort >&2
}
