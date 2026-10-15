# shellcheck shell=bash
# Stage 50: Raspberry Pi 4/5 preinstalled disk image (arm64 only).
#
# Built from the arm64 Ingot rootfs: swaps the generic UEFI kernel/GRUB for
# Ubuntu's linux-raspi kernel and Raspberry Pi boot firmware, boots the kernel
# directly from the FAT boot partition (config.txt), and creates the first user
# with GNOME Initial Setup on first boot. Assembled from filesystem images with
# sfdisk + dd, so no loop devices or mounts are needed on the build host.

RPI_PURGE="casper calamares calamares-settings-ubuntu-common-data iron-installer-config \
 grub-efi-arm64-signed grub-efi-arm64-bin grub-efi-arm64 grub-common grub2-common shim-signed \
 os-prober mokutil"

stage_rpi() {
    [[ "${ARCH}" == arm64 ]] || die "the Raspberry Pi image is arm64 only"
    [[ -x "${ROOTFS}/usr/bin/gnome-shell" ]] || die "run the system stage for arm64 first"
    local rpi="${WORK}/rpi-rootfs" boot="${WORK}/rpi-boot" name="iron-ingot-${INGOT_VERSION}-rpi-arm64-${PROFILE}"
    local img="${OUTDIR}/${name}.img"

    log "copying rootfs for the Raspberry Pi variant"
    chroot_umount
    [[ -d "${rpi}" ]] && safe_rm_tree "${rpi}"
    cp -a --reflink=auto "${ROOTFS}" "${rpi}"

    local saved="${ROOTFS}"
    ROOTFS="${rpi}"
    chroot_mount
    apt_chroot update || true
    log "installing Raspberry Pi kernel and firmware"
    mkdir -p "${rpi}/boot/firmware" "${rpi}/etc/flash-kernel"
    # flash-kernel cannot probe the board inside a chroot; Pi 4 entries cover the
    # common bcm2711/bcm2712 handling, and on the device it re-detects the model.
    echo "Raspberry Pi 4 Model B" > "${rpi}/etc/flash-kernel/machine"
    apt_chroot install linux-raspi linux-firmware-raspi flash-kernel cloud-guest-utils gnome-initial-setup \
        pi-bluetooth 2>&1 | tail -n 5 || apt_chroot install linux-raspi linux-firmware-raspi flash-kernel \
        cloud-guest-utils gnome-initial-setup
    rm -f "${rpi}/etc/flash-kernel/machine"
    local present=() p
    # shellcheck disable=SC2016 # dpkg-query format strings
    for p in ${RPI_PURGE} $(in_chroot dpkg-query -W -f='${Package}\n' 'linux-image-*generic*' 'linux-modules-*generic*' 'linux-generic*' 2>/dev/null); do
        in_chroot dpkg-query -W -f='${Status}' "${p}" 2>/dev/null | grep -q "ok installed" && present+=("${p}")
    done
    [[ ${#present[@]} -gt 0 ]] && apt_chroot purge "${present[@]}"
    apt_chroot autoremove --purge
    in_chroot apt-get clean
    write_rpi_config
    chroot_umount
    ROOTFS="${saved}"

    log "assembling boot partition"
    rm -rf "${boot}"; mkdir -p "${boot}"
    local kver
    kver="$(basename "$(find "${rpi}/boot" -maxdepth 1 -name 'vmlinuz-*-raspi' | sort -V | tail -n 1)")"
    kver="${kver#vmlinuz-}"
    [[ -n "${kver}" ]] || die "linux-raspi kernel not found"
    cp -L "${rpi}/boot/vmlinuz-${kver}" "${boot}/vmlinuz"
    cp -L "${rpi}/boot/initrd.img-${kver}" "${boot}/initrd.img"
    cp "${rpi}"/usr/lib/linux-firmware-raspi/* "${boot}/"
    local dtbdir="${rpi}/lib/firmware/${kver}/device-tree"
    find "${dtbdir}/broadcom" -name 'bcm27*-rpi-*.dtb' -exec cp {} "${boot}/" \;
    cp -r "${dtbdir}/overlays" "${boot}/overlays"
    cp "${rpi}/boot/firmware/config.txt" "${rpi}/boot/firmware/cmdline.txt" "${boot}/"
    : > "${rpi}/boot/firmware/.keep"

    log "creating filesystem images"
    local bootimg="${WORK}/rpi-boot.vfat" rootimg="${WORK}/rpi-root.ext4"
    rm -f "${bootimg}" "${rootimg}"
    mkfs.vfat -C -F 32 -n system-boot "${bootimg}" $((512 * 1024)) >/dev/null
    mcopy -s -i "${bootimg}" "${boot}"/* ::/
    local used_mib root_mib
    used_mib=$(( $(du -sx --block-size=1M "${rpi}" | cut -f1) ))
    root_mib=$(( used_mib + used_mib / 4 + 1024 ))
    truncate -s "${root_mib}M" "${rootimg}"
    mkfs.ext4 -q -F -L writable -d "${rpi}" "${rootimg}"

    log "partitioning ${img}"
    local total_mib=$(( 4 + 512 + root_mib ))
    rm -f "${img}"
    truncate -s "${total_mib}M" "${img}"
    sfdisk --quiet "${img}" <<EOF
label: dos
unit: sectors
start=8192, size=$((512 * 2048)), type=c, bootable
start=$((8192 + 512 * 2048)), type=83
EOF
    dd if="${bootimg}" of="${img}" bs=1M seek=4 conv=notrunc,sparse status=none
    dd if="${rootimg}" of="${img}" bs=1M seek=$((4 + 512)) conv=notrunc,sparse status=none
    rm -f "${bootimg}" "${rootimg}"
    (cd "${OUTDIR}" && sha256sum "$(basename "${img}")" > "$(basename "${img}").sha256")
    log "compressing (xz)"
    xz -T0 -6 -k -f "${img}"
    (cd "${OUTDIR}" && sha256sum "$(basename "${img}").xz" > "$(basename "${img}").xz.sha256")
    log "Raspberry Pi image: ${img}.xz ($(du -h "${img}.xz" | cut -f1)); hardware validation pending"
}

write_rpi_config() {
    cat > "${ROOTFS}/boot/firmware/config.txt" <<'EOF'
# Iron Linux Ingot - Raspberry Pi 4/5
[all]
kernel=vmlinuz
cmdline=cmdline.txt
initramfs initrd.img followkernel
arm_64bit=1
dtoverlay=vc4-kms-v3d
disable_overscan=1
max_framebuffers=2

[pi4]
arm_boost=1

[pi5]
# Pi 5 uses the RP1 southbridge; the generic KMS overlay above applies.

[all]
EOF
    echo "console=serial0,115200 console=tty1 root=LABEL=writable rootfstype=ext4 rootwait fixrtc quiet splash" \
        > "${ROOTFS}/boot/firmware/cmdline.txt"
    cat > "${ROOTFS}/etc/fstab" <<'EOF'
LABEL=writable     /               ext4   defaults,discard   0 1
LABEL=system-boot  /boot/firmware  vfat   defaults,umask=0077 0 1
EOF
    cat > "${ROOTFS}/etc/systemd/system/iron-grow-root.service" <<'EOF'
[Unit]
Description=Grow the root partition to fill the SD card / disk (first boot)
ConditionPathExists=!/var/lib/iron/root-grown
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'src=$(findmnt -no SOURCE /); disk=/dev/$(lsblk -no PKNAME "$src"); part=$(cat /sys/class/block/$(basename "$src")/partition); growpart "$disk" "$part" || true; resize2fs "$src"; mkdir -p /var/lib/iron; touch /var/lib/iron/root-grown'

[Install]
WantedBy=multi-user.target
EOF
    in_chroot systemctl enable iron-grow-root.service
    # No live user and no installer on preinstalled images: GDM runs GNOME
    # Initial Setup to create the first account.
    rm -f "${ROOTFS}/etc/casper.conf"
    echo "iron-rpi" > "${ROOTFS}/etc/hostname"
    sed -i 's/iron-ingot/iron-rpi/' "${ROOTFS}/etc/hosts"
    : > "${ROOTFS}/etc/machine-id"
}
