# Validation evidence (2026-10-15)

Curated copies of what `tests/vm/` and `tests/shell/` produced; full logs and
disk images stay in the git-ignored `tests/vm/results/`. See `docs/STATUS.md`.

| File | What it shows |
|---|---|
| `live-amd64-report.json` | amd64 live ISO, OVMF/KVM: 15/15 automated checks (run-3 ISO) |
| `live-amd64-secureboot-report.json` | same with Secure Boot enforced (MS keys): 16/16 (run-3 ISO), guest reports SB enabled |
| `live-arm64-report.md` | arm64 live ISO under AAVMF/TCG, manual checks |
| `live-*-desktop.jpg`, `grub-arm64.jpg` | live desktops on both architectures |
| `installer-*.jpg` | Calamares: Ingot steps, LUKS2 layout, completion |
| `installed-login-gdm.jpg`, `installed-desktop.jpg` | first boot of the encrypted install |
| `agent-desktop-in-main-desktop.jpg` | an isolated container agent's desktop viewed from the main desktop |
| `plymouth-shutdown.jpg` | Ingot Plymouth theme at live-session shutdown |
| `iron-settings-*.jpg` | Iron Settings rendered in GNOME Shell 50 |
| `tiling-2x2-headless-shell.jpg` | Iron Tiling 2×2 layout with real windows |

## Development run 3 (2026-10-16)

| File | What it shows |
|---|---|
| `installed-lite-desktop.jpg` | installed **Lite** edition, first login: desktop, not the overview |
| `luks-unlock-plymouth.png` | graphical Ingot LUKS unlock prompt, fresh install from the rebuilt run-3 ISO (was text mode) |
| `updates-installed-vm.txt` | `tests/vm/test-updates.sh`: upgrade, rollback, untrusted key and hostile index against an installed VM, 16/16 |
| `agent-vm-installed-vm.txt` | `tests/vm/test-agent-vm.sh`: VM-backed agent end to end, 11/11 |
| `vm-agent-tasks.jpg` | the VM agent's own desktop with task terminals (approved root command in task 3) |
| `vm-agent-viewer.jpg` | the VM agent's desktop opened in the viewer on the Ingot desktop, live-agent count in the panel |
| `tiling-two-monitors.png` | two-monitor tiling with real virtual-pointer drags (headless GNOME Shell) |
