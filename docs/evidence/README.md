# Validation evidence (2026-10-15)

Curated copies of what `tests/vm/` and `tests/shell/` produced; full logs and
disk images stay in the git-ignored `tests/vm/results/`. See `docs/STATUS.md`.

| File | What it shows |
|---|---|
| `live-amd64-report.json` | amd64 live ISO, OVMF/KVM: 17/17 automated checks |
| `live-amd64-secureboot-report.json` | same with Secure Boot enforced (MS keys): 18/18, guest reports SB enabled |
| `live-arm64-report.md` | arm64 live ISO under AAVMF/TCG, manual checks |
| `live-*-desktop.jpg`, `grub-arm64.jpg` | live desktops on both architectures |
| `installer-*.jpg` | Calamares: Ingot steps, LUKS2 layout, completion |
| `installed-login-gdm.jpg`, `installed-desktop.jpg` | first boot of the encrypted install |
| `agent-desktop-in-main-desktop.jpg` | an isolated container agent's desktop viewed from the main desktop |
| `plymouth-shutdown.jpg` | Ingot Plymouth theme at live-session shutdown |
| `iron-settings-*.jpg` | Iron Settings rendered in GNOME Shell 50 |
| `tiling-2x2-headless-shell.jpg` | Iron Tiling 2×2 layout with real windows |
