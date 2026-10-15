# Iron Linux Ingot — Architecture

Ingot is a thin, maintained layer on **Ubuntu 26.04 LTS**. Everything that can
come from Ubuntu's signed archives does (kernel, firmware, GNOME, Mesa, NVIDIA
drivers, security updates); Ingot adds a small set of first-party packages and
an image builder. GNOME is not forked: Ingot ships extensions, GSettings
defaults and a GDM theme registered through Ubuntu's own alternatives.

```
┌────────────────────────── Ingot packages (debian/, Architecture: all) ──────────────────────────┐
│ iron-base-files   identity (dpkg-divert of os-release/lsb-release/issue/legal/motd), APT policy │
│                   (snapd blocked, Mozilla Firefox repo), zram, sysctl, GRUB defaults,           │
│                   iron-hwprofile (adaptive defaults), iron-drivers, recovery-mode options       │
│ iron-branding     wallpapers (generated), logo/wordmark, Plymouth theme                          │
│ iron-shell        GNOME Shell extensions: Iron Tiling, Iron Shell (panel + agent indicator);    │
│                   GDM theme = Yaru + Ingot CSS via the gdm-theme.gresource alternative           │
│ iron-desktop-settings  GSettings overrides, GDM dconf                                           │
│ iron-settings     Iron Settings (GTK4/libadwaita)                                                │
│ iron-agent-desktops    iron-agentd (D-Bus, polkit), backends, guest tooling, CLI                 │
│ iron-installer-config  Calamares sequence/branding/post-install (live medium only)              │
│ ingot-desktop-lite / ingot-desktop   metapackages (upgrades pull new components)                │
│ gnotch (optional) repackaged from a pinned upstream commit                                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
          ▲ local signed APT repo (.work/repo)                 ▲ Ubuntu archive + security, Mozilla APT
          │                                                     │
   build/ingot-build:  bootstrap → packages → system → live (ISO) → rpi (Pi 4/5 image, arm64)
```

## Boot chain

| Platform | Chain |
|---|---|
| amd64 UEFI | shim (Microsoft-signed) → GRUB `gcdx64` (Canonical-signed) → signed kernel → casper |
| amd64 BIOS | GRUB i386-pc El Torito / hybrid MBR |
| arm64 UEFI | shim → GRUB `gcdaa64` (signed) → kernel (ARM64 servers, VMs, UEFI laptops) |
| Raspberry Pi 4/5 | Pi firmware (`start4.elf`) → `config.txt` → `vmlinuz`+`initrd.img` (`linux-raspi`) |

The ESP image carries `EFI/ubuntu/grub.cfg` that searches for the marker file
`/.disk/iron-ingot`, so signed GRUB finds the medium regardless of its embedded
search logic. Installed systems use `efiBootloaderId: ubuntu` because
Canonical-signed GRUB reads its configuration from `EFI/ubuntu/`.

## Desktop

* GNOME Shell 50 / Mutter (Wayland; XWayland on demand), GDM.
* Ubuntu Dock (Canonical-maintained) configured as the bottom taskbar;
  AppIndicators; **no** third-party extensions.
* Iron Tiling: per `(workspace, monitor)` layout state with column/row ratio
  arrays (`layout.js`, unit-tested), drag-to-snap overlay, keyboard layouts,
  edge-resize feedback into ratios, GSettings persistence.
* Iron Shell: Ingot panel styling, logo, lock-screen styling, Agent Desktops
  indicator (D-Bus signals, no polling; hidden when the feature is off).
* `iron-hwprofile` runs once at boot, publishes `/run/iron/hardware.json`, and
  writes a dconf system db (`iron-hw`) that turns animations off on
  software-rendered GPUs and disables file indexing on low-memory machines.

## Agent Desktops

See `agent-desktops/README.md`. Key points: root service is D-Bus activated
and idle-exits; every method is polkit-authorised and ownership-checked; the
container backend uses `systemd-nspawn` with a fixed per-agent user-namespace
range, private network, an ext4 disk image as the storage cap and cgroup v2
limits in `iron-agents.slice`; the VM backend runs QEMU as an unprivileged
user with KVM; approvals are bound to request hashes.

## Updates and recovery

* Ubuntu archives (including `-security`) via standard APT; unattended
  security upgrades on by default; GNOME Software for interactive updates.
* Firefox from Mozilla's signed APT repo (pinned priority 1000); snapd pinned
  to -10 so it cannot be pulled in by recommends.
* Ingot's own packages: during image builds they come from the local signed
  repository. **A hosted Ingot APT repository is not published yet**; setting
  `INGOT_APT_URL`/`INGOT_APT_KEY` at build time adds it to images.
* Recovery: GRUB "Advanced options → recovery mode" (friendly-recovery) gains
  *Iron: reset graphics drivers* and *Iron: disable Agent Desktops*; the live
  medium has a *safe graphics* (`nomodeset`) entry and a serial-console entry.

## Reproducibility

`INGOT_SNAPSHOT=YYYYMMDDTHHMMSSZ` builds against `snapshot.ubuntu.com`, pinning
every Ubuntu package version. Each image writes a package manifest
(`out/*.manifest`). Ingot packages get a unique `+t<timestamp>` version per build.
