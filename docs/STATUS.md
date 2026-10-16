# Ingot status — what works, how it was verified, what does not yet

Last updated: 2026-10-16 (development run 3; see "Run 3" at the end for what changed). Legend:
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
| amd64 ISO (UEFI shim→signed GRUB, BIOS hybrid) | Validated (UEFI under OVMF) | `results/live-amd64/report.json` — 15/15 checks (re-run on the run-3 ISO) |
| amd64 BIOS boot path | Implemented | ISO structure only |
| Secure Boot boot with Microsoft keys enrolled (OVMF secboot + MS vars) | Validated — guest reports Secure Boot enabled | `results/live-amd64-sb/report.json` 16/16 (re-run on the run-3 ISO) |
| arm64 UEFI ISO | Validated in emulation (see "ARM64") | `results/live-arm64-manual/` |
| Raspberry Pi 4/5 image | Built, **not booted** (see "Raspberry Pi") | `out/*rpi*.img.xz` |
| `INGOT_SNAPSHOT` reproducible pinning | Implemented, not exercised | |

## Desktop

| Item | State | Evidence |
|---|---|---|
| GNOME Shell 50 Wayland session, XWayland on demand | Validated | live + installed VM |
| Iron Shell (panel, logo, lock-screen styling) active | Validated | live report; lock screen seen in installed VM |
| Ingot GDM theme (gresource alternative) + wordmark | Validated | `results/install-amd64/step-23-gdm.png` |
| Ingot wallpapers / defaults (dark, Inter, dock bottom intellihide) | Validated | live report, screenshots |
| No desktop cube, no third-party extensions | Validated | live report |
| Plymouth Ingot theme | Validated at live shutdown and, after a fix, for the **graphical LUKS unlock prompt** at installed boot (cause was dangling theme symlinks in the initramfs, not KMS timing) | `docs/evidence/luks-unlock-plymouth.png` |
| Terminal palette | Validated: neutral dark palette in Ptyxis on an installed system | `results/inst-lite/s14-terminal.png` |
| Login lands on the desktop, not the overview | Validated (installed Lite and Full) | `docs/evidence/installed-lite-desktop.jpg` |

## Tiling (Iron Tiling)

| Item | State | Evidence |
|---|---|---|
| 2 columns, 3 columns, 2×2, 3×3 | Validated (real GNOME Shell 50, real windows) | `tests/shell/run-shell-tests.sh` 16/16 |
| Gaps / margins, live reflow | Validated | same |
| Per-workspace + per-monitor persistence (GSettings) | Validated, including two virtual monitors and dragging a window between them | same + `shell-test-pointer.sh`; `docs/evidence/tiling-two-monitors.png` |
| Resizable tiles (edge drag moves the boundary, neighbours follow) | Validated (programmatic resize + grab-end) | same |
| Keyboard layout selection / swap / float | Implemented (swap validated) | same |
| Drag-to-snap overlay with modifier / edge snap | Validated with real virtual-pointer drags in headless GNOME Shell (Ctrl-drag snap, edge snap, snap-back); not yet on a physical mouse | `tests/shell/shell-test-pointer.sh` 14/14 |
| Iron Settings → Tiling page | Validated (renders, bound to GSettings) | `results/settings/settings-tiling.png` |

## Installer, updates, recovery

| Item | State | Evidence |
|---|---|---|
| Calamares installer with Ingot branding/sequence | Validated | `results/install-amd64/step-*.png` |
| Guided erase-disk install, UEFI, GPT, LUKS2 root + /boot | Validated (amd64 VM, encrypted) | unlock prompt → GDM → login |
| Users, hostname template, sudo | Validated | |
| Live packages removed after install | Validated | `dpkg -l casper calamares` empty |
| Edition: Full | Validated | install 1 |
| Edition: Lite | Validated after the fix: `ingot-desktop`, GNOME Software, Flatpak, CUPS, Calculator, System Monitor, File Roller and Baobab removed in one batch (no fallback needed), `ingot-desktop-lite` kept, Agent Desktops kept and enabled, `dpkg --audit` clean, no failed units; 4.4 GB used, ~960 MiB RAM at the desktop | `results/inst-lite/` |
| Agent Desktops opt-in in installer | Validated after fix (`enabled = true` in the installed Lite system) | install 2 |
| Drivers option: open-only and recommended | Both ran in VM installs; NVIDIA path not exercised | |
| Clean reboot from the live session (Ingot Plymouth splash, "remove the medium") | Validated | `results/install2/s8.png` |
| Calamares "not connected to the Internet" warning | Fixed and validated: not shown on the welcome page with working networking | `results/inst-lite/s01-welcome.png` |
| Manual partitioning, dual boot | Implemented (Calamares), not exercised | |
| Updates: Ubuntu archives, unattended security updates, GNOME Software | Implemented (standard Ubuntu mechanisms) | |
| Signed Iron package source (`ingot-publish`, `iron-archive-keyring`, `iron-update`) | **Validated locally** against an installed VM: upgrade, rollback (dry run + apply), untrusted key refused, validly signed hostile index cannot replace `bash` or add non-Iron packages — 16/16 (see "Updates") | `docs/evidence/updates-installed-vm.txt` |
| **Hosted Ingot APT repository** | **Not deployed** — needs a public static host and an offline production key (owner decisions, `docs/UPDATES.md`) | |
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
| Panel indicator against a live daemon (live count, approval and finished notifications) | Validated in the installed VM |
| Iron Settings Agent Desktops page against a live daemon | Implemented; page rendered without daemon only |
| Claude Code / Codex runtimes, managed approval hook | Implemented; **not exercised** (needs accounts) |
| VM agents: boot own kernel, cgroup cap (RAM+384 MiB), QEMU as unprivileged user, console preview, 9p control channel | Validated |
| VM agents: visible agent desktop (Xorg on the VM's virtio GPU via QEMU VNC), viewer on the main desktop | Validated (`docs/evidence/vm-agent-viewer.jpg`) |
| VM agents: instructions, done/failed by exit status, approval-gated root command, preview, export, clean stop (6 s), persistence across restart | Validated — `tests/vm/test-agent-vm.sh` 11/11 (`docs/evidence/agent-vm-installed-vm.txt`) |
| Approval banners withdrawn when decided elsewhere (CLI/Settings) | Validated (`results/inst-lite/agent-vm/after-approve.png`) |
| VM shared folders, VM GPU | Planned |

Bugs found and fixed during validation are listed in the git history
(commits after `07d7e11`).

## ARM64

Validated in QEMU `virt` with AAVMF UEFI firmware under TCG emulation
(Neoverse-N1 CPU model; `-cpu max` makes the firmware crawl):
UEFI → shim → signed GRUB → kernel 7.0.0-38-generic aarch64 → live GNOME
Wayland desktop in ~270 s; systemd running with no failed units; Iron Shell,
Iron Tiling and Ubuntu Dock ACTIVE; zram; native arm64 Firefox from Mozilla;
no snapd. Evidence: `results/live-arm64-manual/`. **Not done on arm64**:
installation to disk, Agent Desktops, real ARM64 hardware, KVM on ARM64.
The automated harness could not select GRUB's serial entry on arm64; the
manual procedure is recorded in the evidence file.

## Raspberry Pi

`out/iron-ingot-26.10-dev-rpi-arm64-full.img.xz` (1.8 GB) built with
`linux-raspi`, Pi firmware, direct-boot `config.txt` ([pi4]/[pi5]),
first-boot root growth and GNOME Initial Setup. **Never booted**: QEMU cannot
emulate a Pi 4/5 with display and no hardware was available.

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
to be increased"). Re-checked 2026-10-16: the latest runs (38727059129,
38719428532) failed in 2–4 s with that annotation and no job executed, so **CI
has never run** and nothing here claims it passes. All the same checks pass
locally (`make check`, `tests/shell/run-shell-tests.sh`). GitHub also warns
that `ubuntu-latest` moves to Ubuntu 26 from 2026-10-19. Needs: the account
owner to fix billing (or make the repository public).

## Performance

Measured in a 4-vCPU / 4 GiB KVM guest (software rendering, virtio-vga): live
session reaches a running GNOME desktop with **885 MiB used**; boot to login
prompt 88 s including the live-media integrity check. **No baseline Ubuntu
comparison has been run yet**, so no "faster/lighter than Ubuntu" claim is made.

## Known gaps (open)

* **Encrypted install, intermittent:** one of three Full+LUKS installs in run 3
  failed at "create partition" — the LUKS header was written with a passphrase
  that was not the one in the fields (verified with `cryptsetup
  --test-passphrase`; typing into the guest was correct and cryptsetup's stdin
  handling was checked separately). The retry with the same ISO and script
  succeeded, and so did a third install from the rebuilt ISO. Not reproduced since; cause unknown (Calamares 3.3.14 / KPMcore
  25.12). Evidence: `results/inst-full-fail1/`. Reproduce:
  `tests/vm/install-calamares.sh inst-full out/<iso> full enable open yes`.
* `/etc/crypttab` written by Calamares carries an Arch (mkinitcpio) comment
  header; harmless, cosmetic.
* VM agents: the preview grab is 1280×720 while the agent screen is 1600×900;
  no panel (tint2) visible on the VM agent desktop.
* The Iron Settings Agent Desktops page has still not been exercised against a
  running daemon (the CLI and panel indicator have).
* Shared folders, Internet mode and GPU sharing for container agents, and
  Claude Code / Codex runtimes, remain unexercised (see Agent Desktops).

## Run 3 (2026-10-16): what was done and how to reproduce

All in disposable QEMU/KVM guests on the development machine; nothing was
installed on the host.

| Check | Result | Command |
|---|---|---|
| Offline checks (lint, 48 Python + 85 JS unit checks) | pass | `make check` |
| Rebuilt amd64 ISO from this branch (388 s incremental) | pass | `sudo build/ingot-build --arch amd64 packages system live` |
| Live boot on the rebuilt ISO: UEFI 15/15, Secure Boot (MS keys) 16/16 | pass | `python3 tests/vm/test_live_boot.py --arch amd64 --iso out/… [--secureboot]` |
| Fresh Full+LUKS install from the rebuilt ISO (agents off, drivers auto): graphical unlock prompt, no `cryptdevice=`, hwprofile → software rendering → animations off, no failed units | pass | `tests/vm/install-calamares.sh inst-full3 out/… full disable auto yes`, then `tests/vm/installed-shell.sh inst-full3` |
| Headless GNOME Shell 50: tiling 16/16, pointer + two monitors 14/14 | pass | `tests/shell/run-shell-tests.sh` |
| Lite install (agents on, drivers auto, no encryption) → first boot → login | pass | `tests/vm/install-calamares.sh inst-lite out/iron-ingot-26.10-dev-amd64-full.iso lite enable auto no` |
| Full install with LUKS2 → unlock → GDM → desktop | pass on retry (see gaps) | `tests/vm/install-calamares.sh inst-full out/… full enable open yes` |
| Root shell on an installed VM for scripted checks | helper | `tests/vm/installed-shell.sh NAME` |
| Iron package source end to end | 16/16 | `tests/vm/test-updates.sh inst-lite BASE_DEBS NEW_DEBS` (two builds' `.deb` sets; the VM must have BASE installed) |
| VM agent end to end (nested KVM) | 11/11 (twice, before and after hardening the host-side writes) | `sudo iron-agent image build --vm` in the guest, then `tests/vm/test-agent-vm.sh inst-lite` |
| Container agent, same workflow with the new runner | 11/11 | `tests/vm/test-agent-vm.sh inst-lite container` |

Not repeated in run 3: the arm64 ISO and Raspberry Pi image were not rebuilt
or re-booted (their rows above are from run 2), and nothing ran on physical
hardware.

Bugs found by these runs and fixed (details in the commit messages):
dangling Plymouth theme links in the initramfs (text LUKS prompt);
`iron-hwprofile` reading the virtio-pci transport instead of the GPU driver;
agent tasks reported "working" until someone pressed Enter; VM agent Xorg
started before the GPU driver loaded; VM agents ignored ACPI power-off (every
stop ended in SIGTERM after 30 s); stale approval requests resurfacing after a
restart; `iron-agent stop` returning before the agent stopped; `image build`
silently breaking existing VM agents' overlay disks; approval banners staying
up after a decision. Security review of the diff: the service's root writes
into agent-writable control directories (approval responses, and the new
shutdown request) opened a fixed temp name and would follow a planted symlink;
they now use `O_CREAT|O_EXCL|O_NOFOLLOW` and fd-based chmod/xattr (unit test
added).

Test-environment note: with two 4 GiB test VMs plus nested agent VMs, the host
went 5 GB into swap and a nested QEMU hung in `kvm_async_pf_task_wait_schedule`
(the test VM waiting for the host to page memory in). That is a property of the
test machine, not Ingot; run nested-agent tests with one test VM at a time.
