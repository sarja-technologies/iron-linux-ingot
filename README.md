# Iron Linux — Ingot

Ingot is the primary edition of Iron Linux: an Ubuntu 26.04 LTS–based desktop
operating system with a refined GNOME (Wayland) desktop, built-in tiling,
and **Iron Agent Desktops** — isolated desktops where AI agents work with a
bounded share of your computer while you keep using your own.

> Development branch. See **[docs/STATUS.md](docs/STATUS.md)** for exactly what
> is implemented, what has been tested and how, and what is still planned.
> Nugget (the minimal Labwc edition) is maintained separately.

## What you get

* **Ubuntu underneath** — `apt`, `.deb`, Ubuntu's signed archives and security
  updates, HWE kernel, firmware, NVIDIA drivers via `ubuntu-drivers`.
  No snapd; Firefox is a native `.deb` from Mozilla's signed repository.
* **Ingot desktop** — GNOME Shell 50 on Wayland (XWayland on demand), bottom
  dock, Ingot panel/lock/login styling, original artwork, no third-party
  extensions to install.
* **Iron Tiling** — two/three columns, 2×2 and 3×3 grids, drag-to-snap,
  edge snapping, `Super+Alt+1…4`, gaps, per-workspace and per-monitor
  layouts, resizable tiles with persistent ratios.
* **Iron Settings** — appearance, tiling, Agent Desktops, hardware & drivers,
  updates.
* **Iron Agent Desktops** — containers (systemd-nspawn + user namespaces) or
  VMs (QEMU/KVM) with enforced CPU/memory/storage/time limits, no network or
  host files unless granted, approval gates, snapshots, reviewed exports.
  Off by default, zero cost when unused. → [agent-desktops/README.md](agent-desktops/README.md)
* **Installer** — Calamares: full or lite edition, guided/manual partitioning,
  optional LUKS2 encryption, UEFI (Secure Boot capable), drivers, Agent
  Desktops opt-in. Recovery options in GRUB recovery mode.
* **Both architectures** — amd64 ISO, arm64 UEFI ISO, Raspberry Pi 4/5 image
  from one source tree.
* **Gnotch** (optional) — the extensible top-bar notch, packaged from a pinned
  upstream commit. → [docs/GNOTCH.md](docs/GNOTCH.md)

## Build

```sh
sudo build/ingot-build --arch amd64          # → out/iron-ingot-<ver>-amd64-full.iso
sudo build/ingot-build --arch arm64          # → out/iron-ingot-<ver>-arm64-full.iso
sudo build/ingot-build --arch arm64 rpi      # → out/iron-ingot-<ver>-rpi-arm64-full.img.xz
make check                                   # lint + unit tests
```

Details: [docs/BUILD.md](docs/BUILD.md) · Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ·
Hardware: [docs/HARDWARE.md](docs/HARDWARE.md) · Audit: [docs/AUDIT.md](docs/AUDIT.md)

## Repository layout

```
build/            image builder (bootstrap → packages → system → live → rpi)
debian/           packaging for all Ingot packages (one source, many binaries)
system/           iron-base-files: identity, APT policy, zram, hwprofile, drivers, recovery
branding/         original artwork + generators (wallpapers are generated, not stored)
desktop/shell/    GNOME Shell extensions (Iron Tiling, Iron Shell) + GDM theme
desktop/defaults/ GSettings/GDM defaults
apps/iron-settings/  Iron Settings (GTK4/libadwaita)
agent-desktops/   iron-agentd, backends, guest tooling, CLI
installer/        Calamares configuration and branding
packaging/gnotch/ Gnotch repackaging from a pinned commit
tests/            unit, headless GNOME Shell, QEMU VM tests
```

## Licence

Iron Linux's own code is GPL-3.0-or-later; artwork is CC BY-SA 4.0. Packages
from Ubuntu, Mozilla and others keep their own licences.
