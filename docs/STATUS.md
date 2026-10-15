# Ingot status — what works, how it was verified, what does not yet

Last updated: 2026-10-15 (development run 1). Legend:
**Validated** = exercised end-to-end in this repo with evidence ·
**Implemented** = built and unit/structurally checked, not exercised end-to-end ·
**Experimental** = partly working, known gaps · **Planned** = not implemented.

Evidence paths are under `tests/vm/results/` and `tests/shell/` (screenshots,
serial logs, `report.json`), produced by the commands in `docs/BUILD.md`.

## Build system and images

| Item | State | Evidence |
|---|---|---|
| Reproducible builder (debootstrap → packages → system → live → rpi), one tree for both arches | Validated | amd64 + arm64 full builds |
| Signed local Ingot APT repo, per-build versions | Validated | builds |
| amd64 ISO (UEFI shim→signed GRUB, BIOS hybrid) | Validated (UEFI under OVMF) | `results/live-amd64/report.json` — 17/17 checks |
| amd64 BIOS boot path | Implemented | ISO structure only |
| Secure Boot boot with Microsoft keys enrolled | Implemented, **not yet run** | `test_live_boot.py --secureboot` exists |
| arm64 UEFI ISO | Built; boot test: see "ARM64" below | |
| Raspberry Pi 4/5 image | see "Raspberry Pi" below | |
| `INGOT_SNAPSHOT` reproducible pinning | Implemented, not exercised | |

## Desktop

| Item | State | Evidence |
|---|---|---|
| GNOME Shell 50 Wayland session, XWayland on demand | Validated | live + installed VM |
| Iron Shell (panel, logo, lock-screen styling) active | Validated | live report; lock screen seen in installed VM |
| Ingot GDM theme (gresource alternative) + wordmark | Validated | `results/install-amd64/step-23-gdm.png` |
| Ingot wallpapers / defaults (dark, Inter, dock bottom intellihide) | Validated | live report, screenshots |
| No desktop cube, no third-party extensions | Validated | live report |
| Plymouth Ingot theme | Implemented; installed as default; **text LUKS prompt seen in VM** (likely early-KMS timing in QEMU) | install VM |
| Terminal palette | Gap: Ptyxis keeps Ubuntu's purple palette | screenshot |
| GNOME opens the overview at login (dock `disable-overview-on-startup` not effective) | Gap | screenshots |

## Tiling (Iron Tiling)

| Item | State | Evidence |
|---|---|---|
| 2 columns, 3 columns, 2×2, 3×3 | Validated (real GNOME Shell 50, real windows) | `tests/shell/run-shell-tests.sh` 16/16 |
| Gaps / margins, live reflow | Validated | same |
| Per-workspace + per-monitor persistence (GSettings) | Validated (persistence); multi-monitor **not exercised** (single virtual monitor) | same |
| Resizable tiles (edge drag moves the boundary, neighbours follow) | Validated (programmatic resize + grab-end) | same |
| Keyboard layout selection / swap / float | Implemented (swap validated) | same |
| Drag-to-snap overlay with modifier / edge snap | Implemented; geometry unit-tested (85 checks); **no real pointer-drag test** | `tests/unit/test-tiling-layout.js` |
| Iron Settings → Tiling page | Validated (renders, bound to GSettings) | `results/settings/settings-tiling.png` |

## Installer, updates, recovery

| Item | State | Evidence |
|---|---|---|
| Calamares installer with Ingot branding/sequence | Validated | `results/install-amd64/step-*.png` |
| Guided erase-disk install, UEFI, GPT, LUKS2 root + /boot | Validated (amd64 VM, encrypted) | unlock prompt → GDM → login |
| Users, hostname template, sudo | Validated | |
| Live packages removed after install | Validated | `dpkg -l casper calamares` empty |
| Edition (full/lite) choice | Full validated; **Lite path not exercised** | |
| Agent Desktops opt-in in installer | **Bug found and fixed** (YAML `on`/`off` ids); fix not yet re-run in a fresh install | commit "Installer: avoid YAML boolean ids" |
| Drivers option (ubuntu-drivers) | Ran in VM (no extra drivers needed); NVIDIA path not exercised | |
| Manual partitioning, dual boot | Implemented (Calamares), not exercised | |
| Updates: Ubuntu archives, unattended security updates, GNOME Software | Implemented (standard Ubuntu mechanisms) | |
| **Hosted Ingot APT repository** | **Planned** — installed systems do not yet receive Ingot package updates | |
| Recovery-mode options (reset graphics, disable agents), safe-graphics boot entry | Implemented, not exercised | |

## Agent Desktops

Validated inside an installed Ingot VM (amd64, nested KVM):

| Item | State |
|---|---|
| Feature off by default; D-Bus activated; **daemon exits when idle (no process, no cgroup)** | Validated |
| Enable/disable (polkit), status, presets scaled to host | Validated |
| Agent image build (container rootfs + VM disk/kernel), 273 s | Validated |
| Container agent start; cgroup limits applied (cpuset, CPUQuota, MemoryMax, no swap, DevicePolicy=closed) | Validated |
| Private user namespace (agent UIDs in a high per-agent range) | Validated |
| No network by default (only `lo`); host `/home` invisible | Validated |
| Agent desktop (Xvnc+Openbox) visible from the main desktop | Validated (`step-36-agent-desktop.png`) |
| VNC preview grab (container and VM) | Validated |
| Instructions → runner → outbox; outputs listing (running and stopped) | Validated |
| Export to an owned folder, no overwrite, traversal rejected, foreign-owned destination refused | Validated |
| Approval-gated root command (`iron-elevate`), state `waiting` → approve → executed | Validated |
| Memory limit: offending process OOM-killed, agent keeps running | Validated (after fixing OOM policy) |
| Pause/resume (cgroup freezer), stop, snapshot/restore | Validated |
| Shared folders (idmapped), live revoke | Implemented + unit-tested; **not exercised in VM** |
| Internet mode (pasta) | Implemented; **not exercised** |
| GPU render-node sharing | Implemented; **not exercised** (no GPU in VM) |
| Iron Settings Agent Desktops page / panel indicator against a live daemon | Implemented; page rendered without daemon only |
| Claude Code / Codex runtimes, managed approval hook | Implemented; **not exercised** (needs accounts) |
| VM agents: boot own kernel, cgroup cap (RAM+384 MiB), QEMU as unprivileged user, console preview, 9p control channel | Validated |
| VM agents: visible agent desktop + instruction execution | **Experimental — not working yet** (the in-guest Xvnc session is not what QEMU displays) |
| VM shared folders, VM GPU | Planned |

Bugs found and fixed during validation are listed in the git history
(commits after `07d7e11`).

## ARM64

_Filled in from `results/live-arm64/report.json` — see the end of this file._

## Raspberry Pi

Image build via `build/ingot-build --arch arm64 rpi`. **No boot test**: QEMU
cannot emulate a Pi 4/5 with display, and no hardware was available. See
`docs/HARDWARE.md`.

## Gnotch

| Item | State |
|---|---|
| `gnotch` .deb from pinned commit, installed (not enabled) in images | Validated (present in installed VM) |
| Iron Settings opt-in switch | Implemented |
| Agent Workspace → Iron Agent Desktops connector | Planned (belongs in Gnotch) |

## CI

`.github/workflows/ci.yml` (lint/unit, headless GNOME Shell, package build,
manual ISO). **Not run**: GitHub refused to start jobs for the private
repository ("recent account payments have failed or your spending limit needs
to be increased"). All the same checks pass locally (`make check`,
`tests/shell/run-shell-tests.sh`).

## Performance

Measured in a 4-vCPU / 4 GiB KVM guest (software rendering, virtio-vga): live
session reaches a running GNOME desktop with **885 MiB used**; boot to login
prompt 88 s including the live-media integrity check. **No baseline Ubuntu
comparison has been run yet**, so no "faster/lighter than Ubuntu" claim is made.
