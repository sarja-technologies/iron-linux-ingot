# Milestone 1 — Audit (2026-10-15)

## Ingot working directory

`~/Documents/Iron-Linux/iron-linux-ingot/` was **empty**: no files, no Git
repository, no remote. The brief names `iron-linux-iron/`, which did not exist
when work started; this session was opened in `iron-linux-ingot/`, so that is
where the repository lives. (At 19:05 an empty `iron-linux-iron/` appeared
alongside it — see the final report: the repository can be moved there.)

No GitHub repository named for Ingot exists under `crossainthero-lab`.

## Nugget (reference only, untouched)

At audit time Nugget lived in `~/Documents/ironlinux`; it has since been moved
(by the owner, 19:05) to `~/Documents/Iron-Linux/iron-linux-nugget/`
(remote `crossainthero-lab/IronLinux`, branch `integration/merge-boot-desktop-installer`):

* Debian trixie, `live-build`, Labwc + Waybar/Fuzzel/Mako, greetd, Calamares.
* amd64 ISO boot-tested in QEMU (BIOS path); RPi4 image built, not hardware-tested.
* ~54 GB of root-owned build residue in the working tree.

Per the brief, Labwc was **not** carried into Ingot. Nothing was copied from
Nugget; it was read only to understand prior decisions.

## Host (build machine)

| | |
|---|---|
| OS | Ubuntu 26.04.1 LTS, kernel 7.0.0-38-generic, x86_64 |
| CPU / RAM | Intel i9-11900F (16 threads), 31 GiB |
| GPU | NVIDIA (PCI 10de:2503), proprietary driver |
| Virtualization | KVM available, nested KVM enabled; qemu-user-binfmt for aarch64 |
| Disk | 191 GB free on `/`; `/tmp` is a 16 GB tmpfs (not used for builds) |
| Tools present | debootstrap, live-build, xorriso, squashfs-tools, qemu-system-{x86,aarch64}, OVMF/AAVMF, systemd-nspawn, gh (authenticated) |
| Added for Ingot | debhelper, apt-utils, shellcheck, mtools, dosfstools, grub-efi-amd64-bin, grub-pc-bin, zstd, python3-pil |

## Reference desktop (read from the running session)

GNOME Shell 50.1 on Wayland, `prefer-dark`, accent `slate`, Inter 10, Hack 10
monospace, Yaru-dark icons, WhiteSur-Dark-grey GTK theme, `:minimize,maximize,close`,
Ubuntu Dock at the **bottom**, intellihide (all windows), 48 px icons, fixed
0.58 opacity, dynamic workspaces, mutter edge-tiling off. Extensions: Ubuntu
Dock, User Themes, Just Perfection, Blur my Shell, **Desktop Cube**, Tiling
Shell, AppIndicators. Wallpaper: a blue glass-wave image (1672×941) of unknown
licence.

Ingot keeps the layout and tone (dark, bottom intellihide dock, Inter, button
order, blue glass-wave mood) but: no desktop cube, no third-party extensions,
first-party tiling instead of Tiling Shell, original procedurally generated
wallpapers instead of the unlicensed image.

## Gnotch

`crossainthero-lab/Gnotch`, local clone `~/Documents/GitHub/gnotch` at
`ff7e1b2` (0.1.0, GNOME Shell 50, MIT). Read only; see `docs/GNOTCH.md`.
