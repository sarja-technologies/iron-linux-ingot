# arm64 live ISO — manual validation (2026-10-15)

ISO: out/iron-ingot-26.10-dev-arm64-full.iso
VM: qemu-system-aarch64 -M virt, TCG, -cpu neoverse-n1, 4 vCPU, 4 GiB, AAVMF (UEFI), virtio-gpu-pci
Procedure: tests/vm/vmctl.py (default GRUB entry; serial getty started from the GUI terminal)

| Check | Result |
|---|---|
| UEFI → shim → signed GRUB 2.14 menu | yes (grub.png) |
| Default entry boots to GNOME desktop | yes, ~270 s under emulation (desktop.png) |
| Kernel | 7.0.0-38-generic aarch64 |
| os-release | Iron Linux Ingot 26.10, ID=iron |
| systemd | running, no failed units |
| Session | live user, Type=wayland |
| iron-shell / iron-tiling / ubuntu-dock | ACTIVE / ACTIVE / ACTIVE |
| zram | /dev/zram0 1.9G |
| Firefox | 158.0~build2 arm64, Maintainer Mozilla (native .deb) |
| snapd | absent |
| iron-hwprofile | arch aarch64, vendor arm, 4 threads, tier low |
| Memory used after login | 1848 MiB (llvmpipe under TCG) |

Note: hwprofile counts virtio-gpu without virgl as accelerated; animations
were off anyway because of the low tier. Automated `test_live_boot.py`
selection of the serial GRUB entry did not work on arm64 (keys sent while
the firmware was still initialising); the default entry was used instead.
