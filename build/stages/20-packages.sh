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

    # Archive keys trusted by images: committed public keys plus, for development
    # builds, this machine's local key (only in the builder copy, never committed).
    ensure_signing_key
    if [[ "${INGOT_TRUST_DEV_KEY:-1}" == 1 ]]; then
        install -m644 "$(KEY_DIR)/archive.pub.gpg" "${builder}/src/ingot/packaging/archive-keys/zz-local-dev.gpg"
    fi
    ls "${builder}/src/ingot/packaging/archive-keys/"*.gpg >/dev/null 2>&1 \
        || die "no archive key to trust: commit a public key to packaging/archive-keys/ or set INGOT_TRUST_DEV_KEY=1"

    # Unique, increasing version per build so apt upgrades existing systems/rootfs.
    # ("+bN" must not be used: dpkg treats it as a binNMU and strips it from ${source:Version}.)
    sed -i "1s/(\([^)]*\))/(\1+t$(date -u +%Y%m%d%H%M%S))/" "${builder}/src/ingot/debian/changelog"
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

    # Optional: Gnotch (independent project) from a pinned commit. Never fatal.
    if [[ -n "${INGOT_GNOTCH_SRC:-}" ]]; then
        "${INGOT_ROOT}/packaging/gnotch/build-gnotch-deb.sh" "${INGOT_GNOTCH_SRC}" "${builder}/src" \
            || warn "Gnotch package skipped (see output above); the image builds without it"
    fi

    publish_repo "${builder}/src"
    echo "${src_hash}" > "$(REPO_DIR)/.src-hash"
}

publish_repo() {
    # Built beside the live repo and swapped in atomically, so a build of another
    # architecture that has the old repo bind-mounted is not disturbed. Uses the
    # same publisher (tools/ingot-publish) as the hosted update repository.
    local debdir="$1" final; final="$(REPO_DIR)"
    local repo="${final}.new"
    ensure_signing_key
    log "publishing local APT repo ${final}"
    rm -rf --one-file-system "${repo}"
    "${INGOT_ROOT}/tools/ingot-publish" --repo "${repo}" --suite "${INGOT_CODENAME}" \
        --gnupghome "$(KEY_DIR)" add "${debdir}"/*.deb >&2
    "${INGOT_ROOT}/tools/ingot-publish" --repo "${repo}" --suite "${INGOT_CODENAME}" verify >&2
    GNUPGHOME="$(KEY_DIR)" gpgconf --kill gpg-agent 2>/dev/null || true
    cp "$(KEY_DIR)/archive.pub.gpg" "${repo}/iron-archive-dev.gpg"
    local old
    for old in "${final}".old.*; do
        [[ -d "${old}" ]] && ! findmnt -rn -S "${old}" >/dev/null 2>&1 && rm -rf --one-file-system "${old}"
    done
    [[ -d "${final}" ]] && mv "${final}" "${final}.old.$(date +%s)"
    mv "${repo}" "${final}"
}
