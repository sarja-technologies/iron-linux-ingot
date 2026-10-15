# Building Iron Linux Ingot

Builds run on an **Ubuntu 26.04** (or newer Debian/Ubuntu) host with root via
sudo. Everything happens under `.work/` (root-owned, git-ignored) and results
land in `out/`. Nothing on the host is repartitioned or reconfigured.

## Host requirements

```sh
sudo apt install debootstrap squashfs-tools xorriso mtools dosfstools gnupg apt-utils \
    qemu-user-binfmt qemu-system-x86 qemu-system-arm qemu-utils ovmf qemu-efi-aarch64 \
    shellcheck gjs python3-gi python3-pil libxml2-utils
```

* ~25 GB free disk per architecture (rootfs, squashfs, caches).
* ARM64 builds on an x86-64 host use `qemu-user-binfmt` (slow: ~1–2 h for the
  full desktop). Building natively on ARM64 hardware is much faster.

## Commands

```sh
# Everything for amd64 (bootstrap → packages → system → live ISO)
sudo build/ingot-build --arch amd64

# arm64 UEFI ISO, then the Raspberry Pi 4/5 image from the same rootfs
sudo build/ingot-build --arch arm64
sudo build/ingot-build --arch arm64 rpi

# Lightweight profile
sudo build/ingot-build --arch amd64 --profile lite

# Individual stages (re-run only what changed)
sudo build/ingot-build --arch amd64 packages system live

# Include Gnotch from a checkout at the pinned commit
sudo INGOT_GNOTCH_SRC=~/src/Gnotch build/ingot-build --arch amd64

# Reproducible: pin every Ubuntu package to a snapshot
sudo INGOT_SNAPSHOT=20261015T000000Z build/ingot-build --arch amd64
```

Outputs (`out/`):

| File | What |
|---|---|
| `iron-ingot-<ver>-amd64-full.iso` | amd64 live/installer ISO (UEFI incl. Secure Boot, BIOS) |
| `iron-ingot-<ver>-arm64-full.iso` | arm64 live/installer ISO (UEFI) |
| `iron-ingot-<ver>-rpi-arm64-full.img.xz` | Raspberry Pi 4/5 preinstalled image |
| `*.sha256`, `*.manifest` | checksums and installed-package manifests |

## Checks and tests

```sh
make check                                  # shellcheck, py_compile, schemas, XML, unit tests
tests/shell/run-shell-tests.sh              # tiling in a real headless GNOME Shell 50
tests/shell/screenshot-settings.sh          # renders Iron Settings pages
python3 tests/vm/test_live_boot.py --arch amd64 --iso out/iron-ingot-*-amd64-full.iso [--secureboot]
python3 tests/vm/test_live_boot.py --arch arm64 --iso out/iron-ingot-*-arm64-full.iso
```

VM tests run disposable QEMU guests (OVMF/AAVMF firmware, KVM on amd64, TCG
emulation for arm64 on x86 hosts) and write serial logs, screenshots and a
`report.json` to `tests/vm/results/<scenario>/`.

## Writing to a USB stick

The amd64 ISO is a hybrid image: `sudo dd if=out/iron-ingot-…-amd64-full.iso of=/dev/sdX bs=4M oflag=sync status=progress`
(check `/dev/sdX` carefully). For the Raspberry Pi use Raspberry Pi Imager or
`xz -dc out/…rpi….img.xz | sudo dd of=/dev/sdX bs=4M oflag=sync`.

## Package signing

Local builds sign the Ingot packages' APT repository with a development key
generated in `.work/keys/` (never committed). Images do not keep that source:
installed systems receive Ingot package updates only once a hosted repository
exists (`INGOT_APT_URL` + `INGOT_APT_KEY` at build time). See `docs/STATUS.md`.
