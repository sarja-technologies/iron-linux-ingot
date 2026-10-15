# shellcheck shell=bash
# Stage 40: build the live/installer ISO (casper layout).
#   UEFI:  shim (Microsoft-signed) -> GRUB (Canonical-signed) -> signed kernel,
#          i.e. Secure Boot capable on both amd64 and arm64.
#   BIOS:  amd64 only, GRUB i386-pc El Torito + hybrid MBR (dd-able to USB).

stage_live() {
    [[ -d "${ROOTFS}/boot" ]] || die "rootfs missing; run bootstrap/system first"
    local iso="${WORK}/iso" name="iron-ingot-${INGOT_VERSION}-${ARCH}-${PROFILE}"
    local out="${OUTDIR}/${name}.iso"
    rm -rf --one-file-system "${iso}"
    mkdir -p "${iso}/casper" "${iso}/boot/grub" "${iso}/.disk" "${iso}/EFI/boot"

    local kver
    kver="$(basename "$(find "${ROOTFS}/boot" -maxdepth 1 -name 'vmlinuz-*' | sort -V | tail -n 1)")"
    kver="${kver#vmlinuz-}"
    [[ -n "${kver}" ]] || die "no kernel in rootfs"
    log "kernel ${kver}"
    cp "${ROOTFS}/boot/vmlinuz-${kver}" "${iso}/casper/vmlinuz"
    cp "${ROOTFS}/boot/initrd.img-${kver}" "${iso}/casper/initrd"

    # Disk metadata used by casper and by GRUB to find the medium.
    echo "${INGOT_NAME} ${INGOT_EDITION} ${INGOT_VERSION} \"${INGOT_CODENAME}\" - ${ARCH} ${PROFILE} ($(date -u +%Y%m%d))" > "${iso}/.disk/info"
    : > "${iso}/.disk/iron-ingot"
    echo "full_cd/single" > "${iso}/.disk/cd_type"

    log "squashfs (xz)"
    local bcj=x86; [[ "${ARCH}" == arm64 ]] && bcj=arm
    chroot_umount
    cp "${WORK}/manifest.tsv" "${iso}/casper/filesystem.manifest"
    # Packages the installer removes from the installed system.
    read_list "${INGOT_ROOT}/build/config/packages/30-live.list" > "${iso}/casper/filesystem.manifest-remove"
    mksquashfs "${ROOTFS}" "${iso}/casper/filesystem.squashfs" -noappend -comp xz -Xbcj "${bcj}" \
        -b 1M -mem 2G -processors "$(( $(nproc) > 8 ? 8 : $(nproc) ))" \
        -wildcards -e 'proc/*' 'sys/*' 'dev/*' 'run/*' 'tmp/*' 'var/tmp/*' \
        'var/cache/apt/archives/*.deb' 'var/lib/apt/lists/*' 'root/.cache' >/dev/null
    du -sx --block-size=1 "${ROOTFS}" | cut -f1 > "${iso}/casper/filesystem.size"

    write_grub_cfg "${iso}/boot/grub/grub.cfg"
    build_efi "${iso}"
    [[ "${ARCH}" == amd64 ]] && build_bios "${iso}"
    # Media integrity list checked at boot by casper-md5check (md5sum.txt itself excluded).
    # shellcheck disable=SC2094
    (cd "${iso}" && find . -type f ! -name md5sum.txt ! -path './boot.catalog' -print0 | sort -z \
        | xargs -0 md5sum > md5sum.txt)

    log "xorriso -> ${out}"
    local vol="IRON_INGOT_${ARCH^^}"
    local args=(-as mkisofs -r -V "${vol:0:32}" -J -joliet-long -l -iso-level 3
                -partition_offset 16 -appended_part_as_gpt
                -append_partition 2 0xef "${WORK}/efi.img"
                -c /boot.catalog)
    if [[ "${ARCH}" == amd64 ]]; then
        args+=(--grub2-mbr "${WORK}/boot_hybrid.img" --mbr-force-bootable
               -b /boot/grub/i386-pc/eltorito.img -no-emul-boot -boot-load-size 4 -boot-info-table --grub2-boot-info
               -eltorito-alt-boot)
    fi
    args+=(-e '--interval:appended_partition_2:::' -no-emul-boot -o "${out}" "${iso}")
    xorriso "${args[@]}" 2>&1 | grep -vE '^xorriso : UPDATE|^$' | tail -n 5 >&2
    (cd "${OUTDIR}" && sha256sum "$(basename "${out}")" > "$(basename "${out}").sha256")
    log "ISO: ${out} ($(du -h "${out}" | cut -f1))"
}

write_grub_cfg() {
    local serial="ttyS0" extra=""
    [[ "${ARCH}" == arm64 ]] && serial="ttyAMA0"
    cat > "$1" <<EOF
# Iron Linux Ingot live/installer media
set default=0
set timeout=5
set timeout_style=menu
insmod all_video
insmod gfxterm
insmod png
loadfont unicode
set menu_color_normal=light-gray/black
set menu_color_highlight=white/blue

menuentry "Try or Install Iron Linux Ingot" --class iron {
    set gfxpayload=keep
    linux   /casper/vmlinuz boot=casper quiet splash ${extra} ---
    initrd  /casper/initrd
}
menuentry "Iron Linux Ingot (safe graphics)" --class iron {
    set gfxpayload=keep
    linux   /casper/vmlinuz boot=casper nomodeset quiet splash ---
    initrd  /casper/initrd
}
menuentry "Iron Linux Ingot (serial console, diagnostics)" --class iron {
    linux   /casper/vmlinuz boot=casper console=tty0 console=${serial},115200 systemd.show_status=1 ---
    initrd  /casper/initrd
}
if [ "\$grub_platform" = "efi" ]; then
menuentry "UEFI firmware settings" { fwsetup }
fi
EOF
}

build_efi() {
    local iso="$1" efi_arch=x64 grub_dir=x86_64-efi
    [[ "${ARCH}" == arm64 ]] && { efi_arch=aa64; grub_dir=arm64-efi; }
    local shim="${ROOTFS}/usr/lib/shim/shim${efi_arch}.efi.signed.latest"
    [[ -f "${shim}" ]] || shim="${ROOTFS}/usr/lib/shim/shim${efi_arch}.efi.signed"
    local mm="${ROOTFS}/usr/lib/shim/mm${efi_arch}.efi"
    local grub="${ROOTFS}/usr/lib/grub/${grub_dir}-signed/gcd${efi_arch}.efi.signed"
    [[ -f "${shim}" && -f "${grub}" ]] || die "signed shim/grub missing in rootfs (${shim}, ${grub})"

    cp "${shim}" "${iso}/EFI/boot/${EFI_BOOT_NAME,,}"
    cp "${grub}" "${iso}/EFI/boot/grub${efi_arch}.efi"
    [[ -f "${mm}" ]] && cp "${mm}" "${iso}/EFI/boot/mm${efi_arch}.efi"
    # Unsigned modules for non-Secure-Boot use (signed GRUB has the common ones built in).
    if [[ -d "${ROOTFS}/usr/lib/grub/${grub_dir}" ]]; then
        mkdir -p "${iso}/boot/grub/${grub_dir}"
        cp "${ROOTFS}/usr/lib/grub/${grub_dir}/"*.mod "${ROOTFS}/usr/lib/grub/${grub_dir}/"*.lst "${iso}/boot/grub/${grub_dir}/" 2>/dev/null || true
    fi
    cp "${ROOTFS}/usr/share/grub/unicode.pf2" "${iso}/boot/grub/font.pf2" 2>/dev/null || true
    mkdir -p "${iso}/boot/grub/fonts"
    cp "${ROOTFS}/usr/share/grub/unicode.pf2" "${iso}/boot/grub/fonts/unicode.pf2" 2>/dev/null || true

    # Signed GRUB reads EFI/ubuntu/grub.cfg from the ESP: point it at the ISO's config.
    local esp="${WORK}/esp"
    rm -rf "${esp}"; mkdir -p "${esp}/EFI/boot" "${esp}/EFI/ubuntu"
    cp "${iso}/EFI/boot/"* "${esp}/EFI/boot/"
    cat > "${esp}/EFI/ubuntu/grub.cfg" <<'EOF'
search --set=root --file /.disk/iron-ingot
set prefix=($root)/boot/grub
configfile $prefix/grub.cfg
EOF
    cp "${esp}/EFI/ubuntu/grub.cfg" "${esp}/EFI/boot/grub.cfg"
    local size_kb=$(( $(du -sk "${esp}" | cut -f1) + 1024 ))
    rm -f "${WORK}/efi.img"
    mkfs.vfat -C -n IRON_EFI "${WORK}/efi.img" "${size_kb}" >/dev/null
    mcopy -s -i "${WORK}/efi.img" "${esp}/EFI" ::/
}

build_bios() {
    local iso="$1"
    mkdir -p "${iso}/boot/grub/i386-pc"
    cp "${ROOTFS}/usr/lib/grub/i386-pc/"*.mod "${ROOTFS}/usr/lib/grub/i386-pc/"*.lst "${iso}/boot/grub/i386-pc/"
    chroot_mount
    in_chroot grub-mkimage -O i386-pc-eltorito -p /boot/grub -o /tmp/eltorito.img \
        biosdisk iso9660 part_msdos part_gpt normal search search_fs_file configfile linux \
        echo test all_video gfxterm font png
    chroot_umount
    mv "${ROOTFS}/tmp/eltorito.img" "${iso}/boot/grub/i386-pc/eltorito.img"
    cp "${ROOTFS}/usr/lib/grub/i386-pc/boot_hybrid.img" "${WORK}/boot_hybrid.img"
}
