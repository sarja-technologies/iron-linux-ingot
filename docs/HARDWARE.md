# Hardware support

Ingot uses Ubuntu 26.04's HWE kernel (7.0 series), `linux-firmware`, Mesa and
Ubuntu's driver tooling, so hardware support tracks Ubuntu 26.04 Desktop.
"Validated" below means tested in this repository; everything else is
expected from the Ubuntu stack but **not yet verified on real hardware**.

## x86-64 / AMD64

| Area | Support | Validated |
|---|---|---|
| Intel / AMD CPUs (x86-64-v1+) | generic kernel, `intel-microcode`, `amd64-microcode`, `thermald` (Intel) | QEMU/KVM on Intel i9-11900F host |
| UEFI | shim + signed GRUB + signed kernel | OVMF (see `docs/STATUS.md` for Secure Boot result) |
| Legacy BIOS | GRUB i386-pc El Torito / hybrid MBR (live medium) | build only |
| Intel graphics | Mesa `iris`/`crocus`, Vulkan `anv` | not on hardware |
| AMD graphics | Mesa `radeonsi`, Vulkan `radv` | not on hardware |
| NVIDIA graphics | `nouveau` by default; proprietary driver via installer option or `iron-drivers install` (Ubuntu `nvidia-driver-*`, signed modules for Secure Boot) | detection only (host RTX 30-series seen as `0x10de:0x2503`) |
| Wi-Fi / Bluetooth | kernel + `linux-firmware`; Broadcom via `ubuntu-drivers` | not on hardware |
| Suspend / hibernate | systemd defaults; hibernate not configured (zram swap only) | not tested |

## ARM64 / AArch64

| Target | Image | Validated |
|---|---|---|
| ARM64 UEFI machines (servers, Ampere, VMs, Snapdragon X laptops with UEFI) | `iron-ingot-…-arm64-full.iso` | QEMU `virt` + AAVMF (TCG emulation) — see `docs/STATUS.md` |
| Raspberry Pi 4 (4–8 GB recommended) | `iron-ingot-…-rpi-arm64-full.img.xz` | **image build only; no hardware test** |
| Raspberry Pi 5 | same image (`[pi5]` section, `bcm2712` DTBs from `linux-raspi`) | **image build only; no hardware test** |

Known ARM64 limitations:

* Snapdragon/Apple-silicon laptops need device trees and firmware not in
  Ubuntu's generic kernel today; Apple silicon is unsupported.
* The Raspberry Pi image is GNOME on V3D (Pi 4/5). Expect a 4 GB Pi to be
  usable but not fast; Agent Desktops on a Pi should use the Light preset.
* VM agents on ARM64 need KVM on ARM64 hardware; under emulation they are slow.
* QEMU cannot boot the Pi image as a Raspberry Pi (no usable `raspi4b`
  graphics path), so the Pi image has not been booted anywhere yet.

## Adaptive performance

`iron-hwprofile` classifies the machine at boot (`/run/iron/hardware.json`):

| Tier | Rule | Defaults applied |
|---|---|---|
| low | < 6 GiB RAM or ≤ 2 threads | animations off, file indexing off |
| standard | otherwise | upstream GNOME defaults |
| high | ≥ 16 GiB RAM and ≥ 8 threads | upstream GNOME defaults |

Software rendering (no 3D-capable DRM driver, e.g. basic VM graphics) also
turns animations off. All are dconf defaults: users can change them.
