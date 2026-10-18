# Iron Linux — Ingot

**A complete desktop operating system that respects the hardware it runs on.**

Ingot is the primary edition of Iron Linux, built by [Sarja Technologies](https://github.com/sarja-technologies).
It is a maintained layer on top of Ubuntu 26.04 LTS and GNOME 50: the same
signed archives, kernel, firmware and security updates, with a considered
desktop, first-party window tiling, a unified settings application, and a new
way to let AI agents work on your computer without handing them the keys to it.

> **Status: active development, pre-release.** There is no released version and
> no hosted package repository yet. Much of the system has been built and
> exercised in virtual machines; almost nothing has run on physical hardware.
> [`docs/STATUS.md`](docs/STATUS.md) is the authoritative record of what is
> validated, what is only implemented, and what is planned, and this README
> defers to it. See [What is real today](#what-is-real-today).

---

## Why Iron Linux exists

Desktop Linux has two familiar failure modes.

One is the **heavy default**: a full-featured distribution that is capable and
well supported, but whose out-of-the-box experience spends a lot of memory,
animates on hardware that cannot afford it, and leaves you assembling the
finishing touches yourself: tiling, extensions, theming, sensible defaults.

The other is the **minimal retreat**: a lean window manager and a pile of
scripts. It is light, but you pay for the lightness in missing functionality
and in time spent building your own desktop.

Iron Linux is an attempt to refuse that trade. The goal is a desktop that is
**complete and beautiful *and* efficient**, where efficiency comes from
choosing sensible behaviour per machine, not from removing capability.

Two further problems shaped the project:

* **Window management should be part of the system.** Tiling is currently
  something you bolt on with third-party extensions that break when GNOME
  updates. Ingot ships it as a first-party, tested component.
* **AI agents are arriving on the desktop with no containment story.** The
  common pattern is to run an agent as you, with all your files and
  credentials, and hope. Ingot treats an agent as something that deserves its
  own bounded environment, with limits you set and approvals you control.

## What "Ingot" means

An ingot is refined metal cast into a form that can be worked into something
else: neither raw ore nor a finished tool. That is the role of this edition.
It is the full, general-purpose foundation of Iron Linux: more than a minimal
base, intended as the thing you build your daily environment on.

The name also marks the family. **Nugget** is the separate, minimal edition
(Labwc-based, Debian live-build) and is maintained in its own repository.
Ingot does not reuse Nugget's compositor or code; the two are different
answers to different needs.

## Design principles

1. **Complete, not minimal.** Functionality is not traded away to win a
   benchmark. Lite exists as an *edition* that removes optional applications;
   the desktop itself stays whole.
2. **Efficient by adaptation.** The system measures the machine at boot and
   adjusts defaults to it (see [Adaptive behaviour](#adaptive-behaviour)),
   instead of assuming a single class of hardware.
3. **Ubuntu underneath, not forked.** Everything that can come from Ubuntu
   does. Ingot adds a small set of first-party packages and an image builder.
   GNOME is extended and configured, never patched.
4. **The user stays in control.** Defaults are dconf/GSettings values you can
   change. Features such as Agent Desktops are off until you turn them on.
   Nothing is locked.
5. **Isolation is enforced, not implied.** Limits come from the kernel
   (cgroups, namespaces, hardware virtualization), not from a policy file an
   agent could ignore.
6. **Say what has been tested.** Claims in this project's documentation are
   tied to evidence or labelled as not yet verified.

## The desktop

Ingot's desktop is GNOME Shell 50 on Wayland (XWayland on demand), with GDM, a
bottom intellihide dock (Ubuntu Dock, maintained by Canonical), AppIndicators,
and Ingot's own panel, lock-screen, login and boot styling. Wallpapers and
branding are original, and the wallpapers are generated procedurally rather
than shipped as images. There are no third-party shell extensions to install
or to break on upgrade, and no desktop cube.

The intent is a desktop that feels fluid and cohesive: coherent typography
(Inter), a dark default, consistent theming from the boot splash through the
login screen to the lock screen, and motion that is kept on where the hardware
can sustain it. Animation smoothness and responsiveness are design goals; they
have **not** been benchmarked against stock Ubuntu (see
[Performance](#performance)).

### Iron Tiling

First-party window tiling, implemented as a GNOME Shell extension and designed
to be a core part of the desktop rather than an add-on.

* Layouts: two columns, three columns, 2×2 and 3×3 grids.
* Layout state per `(workspace, monitor)`, persisted in GSettings.
* Drag-to-snap overlay with modifier and edge snapping.
* Resizable tiles: dragging an edge moves the boundary and neighbouring tiles
  follow; ratios persist.
* Gaps and margins, with live reflow.
* Keyboard control: `Super+Alt+1…4` select layouts, `Super+Alt+0` turns
  tiling off, `Super+Alt+Space` cycles, `Super+Alt+←↑↓→` swaps tiles,
  `Super+Alt+F` floats or re-tiles a window.

Layouts, gaps, resizing and persistence are tested in a real headless GNOME
Shell 50 with real windows. Drag-to-snap geometry is unit-tested, but there is
no real pointer-drag test on `develop`, and multiple monitors have not been
exercised here (both are covered on `stabilise/phase-3`, below).

### Iron Settings

A GTK4/libadwaita application that gathers the Ingot-specific controls in one
place: appearance, tiling, Agent Desktops, hardware and drivers, and updates.
The Tiling page is bound to the same GSettings keys the extension reads. The
Agent Desktops page has been rendered but not yet exercised against a live
daemon.

### Adaptive behaviour

`iron-hwprofile` runs once at boot and classifies the machine (published at
`/run/iron/hardware.json`). It writes ordinary dconf defaults:

| Tier | Rule | Defaults applied |
|---|---|---|
| low | < 6 GiB RAM or ≤ 2 threads | animations off, file indexing off |
| standard | otherwise | upstream GNOME defaults |
| high | ≥ 16 GiB RAM and ≥ 8 threads | upstream GNOME defaults |

Software rendering (no 3D-capable DRM driver) also turns animations off.
Memory is compressed with zram. Every one of these is a user-changeable
default.

## Iron Agent Desktops

AI agents are useful and, run naively, risky. Iron Agent Desktops give each
agent its own **separate execution environment**: not a workspace, but a
container or virtual machine with its own desktop that you can watch, instruct,
pause, snapshot and stop, while you keep working on yours.

* **Two isolation levels.** Containers (`systemd-nspawn` with a private user
  namespace per agent) are light and fast to start. Virtual machines
  (QEMU/KVM, running as an unprivileged user, with their own kernel) provide a
  hardware boundary.
* **Enforced resource limits.** CPU threads, CPU time, memory (with no swap
  escape), storage, process count and run time are capped through cgroup v2
  and image size. Presets (Light / Balanced / Heavy / Custom) scale to the
  host, and the service always reserves memory for your own desktop.
  Allocating more than half the machine requires administrator
  authentication.
* **Closed by default.** No network and no access to your files unless you
  grant them. Shared folders are read-only unless made writable and can be
  revoked immediately.
* **Approval gates.** Sensitive actions and root commands wait for you. Each
  approval is bound to a hash of the exact request and is single-use.
* **Costs nothing when unused.** The feature is off by default; when enabled
  with no agents running, the root service is D-Bus-activated and exits when
  idle.
* **Local first.** No remote orchestration service is involved. Runtimes for
  Claude Code and OpenAI Codex CLI are supported, as is running an AgentDock
  AppImage you provide.

The honest limits are documented too: GPU time and memory are shared, not
partitioned; VM agents have no GPU passthrough yet. Full details, including
the enforcement table: [`agent-desktops/README.md`](agent-desktops/README.md).

## Security and user control

* **Ubuntu's trust chain.** Secure Boot uses Microsoft-signed shim and
  Canonical-signed GRUB and kernel. Updates come from Ubuntu's signed archives
  with unattended security upgrades enabled by default.
* **No snap.** `snapd` is blocked by APT policy. Firefox is a native `.deb`
  from Mozilla's signed repository.
* **Disk encryption.** The installer offers LUKS2 for root and `/boot`.
* **Scoped trust for Iron's own packages.** The design gives Ingot's packages a
  separate signed source whose key is trusted *only* for that source, which
  can only supply `iron-*`, `ingot-*` and `gnotch` packages, even if its index
  is signed. See [`docs/UPDATES.md`](docs/UPDATES.md). No such repository is
  hosted yet.
* **Recovery.** GRUB recovery mode gains options to reset graphics drivers and
  to disable Agent Desktops; the live medium has a safe-graphics entry.
* **Your system, your settings.** Ingot's behaviour is expressed as standard
  GSettings, dconf and systemd configuration. Nothing prevents you from
  changing it.

## Hardware and installation

* **amd64** UEFI (Secure Boot capable) and BIOS ISO; **arm64** UEFI ISO;
  a **Raspberry Pi 4/5** image. All come from one source tree.
* Calamares installer with Full and Lite editions, guided or manual
  partitioning, optional LUKS2 encryption, optional proprietary drivers, and an
  opt-in switch for Agent Desktops.
* Ubuntu's HWE kernel, `linux-firmware`, Mesa and `ubuntu-drivers`, so
  hardware support tracks Ubuntu 26.04 Desktop. Details and limitations:
  [`docs/HARDWARE.md`](docs/HARDWARE.md).
* [Gnotch](docs/GNOTCH.md), an independent extensible top-bar notch, can be
  packaged into images from a pinned upstream commit. It is installed but
  disabled by default and never blocks the core build.

## What is real today

The legend follows `docs/STATUS.md`: **validated** means exercised end to end
with evidence in this repository; **implemented** means built and unit or
structurally checked but not exercised end to end.

**Validated (in virtual machines and a headless GNOME Shell)**

* The image builder for amd64 and arm64, with a signed local Ingot APT repo.
* The amd64 ISO booting under UEFI, and under UEFI with Secure Boot enforced
  with Microsoft keys.
* The GNOME Shell 50 Wayland session with Iron Shell, the Ingot GDM theme and
  the Plymouth theme.
* Iron Tiling: all four layouts, gaps, resizing and per-workspace persistence.
* The Calamares install flow: guided erase-disk, UEFI/GPT, LUKS2, Full
  edition, user creation, reboot into the installed system. (The Lite edition
  had a package-removal bug on `develop`; the fix is on `stabilise/phase-3`.)
* The arm64 ISO booting to a live GNOME desktop under QEMU emulation.
* Agent Desktops with container agents: limits, private user namespace, no
  network by default, hidden host files, approvals, snapshots, export.

**Implemented, not yet exercised**

* BIOS boot path, manual partitioning and dual boot, recovery-mode entries.
* Agent shared folders, internet mode, GPU render-node sharing, and the
  Claude Code and Codex runtimes (they need accounts).
* `INGOT_SNAPSHOT` reproducible pinning.

**Built but never run**

* The Raspberry Pi image: no hardware was available and QEMU cannot emulate it.

**Experimental or planned**

* VM agents (own kernel, cgroup caps, console preview are validated; a
  visible desktop and instruction execution are not yet working on this
  branch).
* A hosted Ingot package repository. It needs a public static host and an
  offline production signing key.
* Gnotch's Agent Workspace connecting to Iron Agent Desktops.
* Shared folders and GPU for VM agents.

**Not done anywhere**

* Any test on physical hardware.
* Installation to disk on arm64.
* A continuous-integration run: GitHub has refused to start the workflows.
  The same checks pass locally.

Further validation work is in an open pull request (`stabilise/phase-3`) and is
not part of `develop` until merged: the Lite install fix, the graphical LUKS
unlock prompt, multi-monitor and real-pointer tiling tests, the signed update
and rollback flow (validated against an installed VM), and VM agents working
end to end. Its `docs/STATUS.md` supersedes the one here.

### Performance

The only measurement made so far is one 4-vCPU / 4 GiB KVM guest with software
rendering: the live session reached a running GNOME desktop with **885 MiB
used**, and booted to a login prompt in 88 s including the live-media
integrity check. **No baseline Ubuntu comparison has been run**, so this
project makes no claim to be faster or lighter than Ubuntu. Proving that is an
open task, not an assumption.

## Architecture

Ingot is a thin layer on Ubuntu:

```
Ingot packages (debian/)           iron-base-files · iron-branding · iron-shell
                                   iron-desktop-settings · iron-settings
                                   iron-agent-desktops · iron-installer-config
                                   ingot-desktop / ingot-desktop-lite · gnotch (optional)
        ▲ local signed APT repo                  ▲ Ubuntu archive + security, Mozilla APT
build/ingot-build:  bootstrap → packages → system → live (ISO) → rpi (Pi 4/5 image)
```

Everything else (kernel, firmware, GNOME, Mesa, NVIDIA drivers) is Ubuntu's.
The boot chains, the package layout, `iron-hwprofile`, update and recovery
design, and the reproducibility approach are described in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Longer-term ambitions

These are directions, not commitments or promised dates.

* **Measured efficiency.** Establish baselines against stock Ubuntu on real
  low-end and high-end hardware, then publish the numbers, whatever they show.
* **Real-hardware validation** across Intel, AMD and NVIDIA machines, ARM64
  laptops and servers, and the Raspberry Pi.
* **A hosted, signed Ingot package repository** with rollback, so the system
  updates as a coherent whole.
* **Agent Desktops growth:** GPU access for VM agents, shared folders for VM
  agents, hardware partitioning where the hardware exposes it, and first-class
  integration with tools such as Gnotch.
* **Deeper tiling and multitasking** features built on Iron Tiling's per-monitor
  layout model.
* **Release engineering:** working CI, reproducible release builds, and a
  stable release cadence aligned with Ubuntu LTS.

## Build

On an Ubuntu 26.04 (or newer Debian/Ubuntu) host with `sudo`:

```sh
sudo build/ingot-build --arch amd64          # → out/iron-ingot-<ver>-amd64-full.iso
sudo build/ingot-build --arch arm64          # → out/iron-ingot-<ver>-arm64-full.iso
sudo build/ingot-build --arch arm64 rpi      # → out/iron-ingot-<ver>-rpi-arm64-full.img.xz
make check                                   # lint + unit tests
```

Builds take ~25 GB of disk per architecture under a git-ignored `.work/`;
arm64 on an x86-64 host runs under emulation and is slow. Host packages,
stages, profiles and the VM test harnesses are in
[`docs/BUILD.md`](docs/BUILD.md).

## Repository layout

```
build/             image builder (bootstrap → packages → system → live → rpi)
debian/            packaging for all Ingot packages (one source, many binaries)
system/            iron-base-files: identity, APT policy, zram, hwprofile, drivers, recovery
branding/          original artwork and generators
desktop/shell/     GNOME Shell extensions (Iron Tiling, Iron Shell) and GDM theme
desktop/defaults/  GSettings and GDM defaults
apps/iron-settings/  Iron Settings (GTK4/libadwaita)
agent-desktops/    iron-agentd, backends, guest tooling, CLI
installer/         Calamares configuration and branding
packaging/gnotch/  Gnotch repackaging from a pinned commit
tests/             unit, headless GNOME Shell, QEMU VM tests
docs/              status, architecture, build, hardware, updates, evidence
```

## Documentation

| Document | Contents |
|---|---|
| [`docs/STATUS.md`](docs/STATUS.md) | What is validated, implemented, experimental or planned, with evidence |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Packages, boot chains, desktop, updates, reproducibility |
| [`docs/BUILD.md`](docs/BUILD.md) | Building images, running checks and VM tests |
| [`docs/HARDWARE.md`](docs/HARDWARE.md) | Supported and unverified hardware, adaptive tiers |
| [`docs/UPDATES.md`](docs/UPDATES.md) | Update sources, the Iron package trust model, rollback |
| [`agent-desktops/README.md`](agent-desktops/README.md) | Agent Desktops usage, enforcement, limits |
| [`docs/GNOTCH.md`](docs/GNOTCH.md) | Gnotch packaging and the planned connector |
| [`docs/AUDIT.md`](docs/AUDIT.md) | Project starting-point audit |
| [`docs/evidence/`](docs/evidence/README.md) | Screenshots and reports from validation runs |

## Licence

Iron Linux's own code is GPL-3.0-or-later; artwork is CC BY-SA 4.0 (provisional,
pending a compatibility audit). Packages from Ubuntu, Mozilla and others keep
their own licences. See [`LICENSE`](LICENSE).
