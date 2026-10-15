#!/usr/bin/env python3
"""Boot an Ingot live ISO under UEFI and validate the running system.

usage: tests/vm/test_live_boot.py --arch amd64 --iso out/...iso [--secureboot] [--out DIR]

Evidence (serial log, screenshots, JSON report) is written to --out.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingotvm import VM  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", default="amd64", choices=["amd64", "arm64"])
    ap.add_argument("--iso", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--secureboot", action="store_true")
    ap.add_argument("--memory", type=int, default=4096)
    ap.add_argument("--boot-timeout", type=int, default=None)
    args = ap.parse_args()
    slow = args.arch == "arm64" and os.uname().machine != "aarch64"  # TCG emulation
    boot_timeout = args.boot_timeout or (2400 if slow else 600)
    tag = f"live-{args.arch}{'-sb' if args.secureboot else ''}"
    out = os.path.abspath(args.out or os.path.join(os.path.dirname(__file__), "results", tag))
    os.makedirs(out, exist_ok=True)
    report = {"scenario": tag, "iso": os.path.abspath(args.iso), "started": time.strftime("%FT%TZ", time.gmtime()),
              "checks": {}, "facts": {}}
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        report["checks"][name] = {"pass": bool(cond), "detail": detail[-2000:] if isinstance(detail, str) else detail}
        print(f"{'ok  ' if cond else 'FAIL'} {name}" + (f": {detail.strip()[:200]}" if not cond and detail else ""))
        ok = ok and bool(cond)

    vm = VM(args.arch, out, iso=args.iso, memory=args.memory, secureboot=args.secureboot, name="vm")
    t0 = time.time()
    with vm:
        # Firmware + GRUB menu, then select the serial diagnostics entry (2nd from bottom on
        # EFI: "...serial console", "UEFI firmware settings").
        # Wait until GRUB's menu is actually on screen (firmware is very slow under
        # TCG emulation), detected as a frame with a meaningful amount of text.
        grub_png = os.path.join(out, "01-grub.png")
        deadline = time.time() + (600 if slow else 60)
        while time.time() < deadline:
            time.sleep(2)
            vm.serial_text()  # keep draining serial: a full socket buffer stalls the guest
            vm.screendump(grub_png)
            if screen_has_menu(grub_png):
                break
        time.sleep(1)
        for _ in range(8):
            vm.key("down")
        vm.key("up")
        vm.screendump(os.path.join(out, "02-grub-selected.png"))
        vm.key("ret")
        try:
            vm.wait_serial(r"Linux version", timeout=300 if slow else 90)
            check("kernel started", True)
        except (TimeoutError, RuntimeError) as e:
            vm.screendump(os.path.join(out, "fail-kernel.png"))
            check("kernel started", False, str(e))
            raise SystemExit(finalize(report, out, False))
        report["facts"]["kernel_seconds"] = round(time.time() - t0, 1)

        try:
            vm.wait_serial(r"(?i)iron-ingot login:", timeout=boot_timeout)
            check("serial login prompt", True)
        except (TimeoutError, RuntimeError) as e:
            vm.screendump(os.path.join(out, "fail-login.png"))
            check("serial login prompt", False, str(e))
            raise SystemExit(finalize(report, out, False))
        report["facts"]["login_prompt_seconds"] = round(time.time() - t0, 1)

        vm.send_serial("iron\n")
        time.sleep(3)
        if "assword" in vm.serial_text()[-200:]:
            vm.send_serial("\n")
        vm.wait_serial(r"iron@iron-ingot:.*\$ ", timeout=60)
        # systemd >= 257 shell integration prints OSC 3008 context via PROMPT_COMMAND.
        vm.run("unset PROMPT_COMMAND; bind 'set enable-bracketed-paste off' 2>/dev/null; "
               "export TERM=dumb PAGER=cat SYSTEMD_PAGER=cat LANG=C.UTF-8 PS1='$ '; stty cols 200 -echo")

        rc, state = vm.run("timeout 600 systemctl is-system-running --wait", timeout=660)
        state = state.strip().splitlines()[-1] if state.strip() else ""
        report["facts"]["system_state"] = state
        report["facts"]["system_ready_seconds"] = round(time.time() - t0, 1)
        _, failed = vm.run("systemctl --failed --no-legend --plain | awk '{print $1}'")
        check("systemd running (no failed units)", state == "running", f"state={state} failed={failed.split()}")
        report["facts"]["failed_units"] = failed.split()

        _, osr = vm.run("cat /etc/os-release")
        check("os-release is Iron Linux", 'NAME="Iron Linux"' in osr and "ID=iron" in osr, osr)
        _, uname = vm.run("uname -rm")
        report["facts"]["kernel"] = uname.strip()

        # Graphical session: live user auto-logged into a Wayland GNOME session.
        sess = ""
        for _ in range(60):
            _, sess = vm.run("for s in $(loginctl list-sessions --no-legend | awk '{print $1}'); do "
                             "loginctl show-session $s -p Name -p Type -p Class -p State; echo; done")
            if "Name=iron" in sess and "Type=wayland" in sess and "Class=user" in sess:
                break
            time.sleep(5)
        check("GNOME Wayland session for live user", "Type=wayland" in sess and "Name=iron" in sess, sess)
        _, shell = vm.run("pgrep -a gnome-shell | head -n 3")
        check("gnome-shell running", "gnome-shell" in shell, shell)
        _, xw = vm.run("pgrep -a Xwayland || echo 'not started (on demand)'")
        report["facts"]["xwayland"] = xw.strip()

        bus = "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u iron)/bus"
        _, exts = vm.run(f"{bus} gnome-extensions list --enabled")
        report["facts"]["enabled_extensions"] = exts.split()
        for uuid in ("iron-shell@ironlinux.org", "iron-tiling@ironlinux.org", "ubuntu-dock@ubuntu.com"):
            _, info = vm.run(f"{bus} gnome-extensions info {uuid} | grep -i state")
            check(f"extension active: {uuid}", "ACTIVE" in info.upper(), info)
        _, cube = vm.run(f"{bus} gnome-extensions list | grep -ci cube || true")
        check("no desktop-cube extension", cube.strip() in ("0", ""), cube)
        _, wp = vm.run(f"{bus} gsettings get org.gnome.desktop.background picture-uri")
        check("Ingot wallpaper default", "ingot-dawn" in wp, wp)

        _, zram = vm.run("swapon --show=NAME,TYPE,SIZE --noheadings")
        check("zram swap active", "zram" in zram, zram)
        _, snap = vm.run("command -v snap || dpkg -l snapd 2>/dev/null | grep -c ^ii || echo none")
        check("snapd absent", "snap" not in snap.split("\n")[0] or snap.strip() == "none", snap)
        _, ff = vm.run("apt-cache policy firefox | sed -n '1,4p'")
        report["facts"]["firefox_policy"] = ff
        # Live media carry no APT lists, so check the package itself and the configured source.
        _, ffo = vm.run("dpkg-query -W -f='${Version} | ${Maintainer}\\n' firefox; "
                        "grep -h '^URIs' /etc/apt/sources.list.d/mozilla.sources")
        check("firefox is a native .deb from Mozilla",
              "snap" not in ffo.split("\n")[0] and "mozilla" in ffo.split("\n")[0].lower()
              and "packages.mozilla.org" in ffo, ffo)
        _, hw = vm.run("cat /run/iron/hardware.json")
        try:
            report["facts"]["hardware"] = json.loads(hw)
            check("hardware profile detected", True)
        except ValueError:
            check("hardware profile detected", False, hw)
        _, mem = vm.run("free -m | awk '/Mem:/{print $3}'")
        report["facts"]["used_memory_mib_after_login"] = mem.strip()
        _, sb = vm.run("mokutil --sb-state 2>&1 || true")
        report["facts"]["secureboot"] = sb.strip()
        if args.secureboot:
            check("Secure Boot enabled in guest", "enabled" in sb.lower(), sb)
        _, journal_err = vm.run("journalctl -b -p err --no-pager -q | tail -n 40")
        report["facts"]["journal_errors_tail"] = journal_err

        time.sleep(5)
        vm.screendump(os.path.join(out, "10-desktop.png"))
        report["facts"]["total_seconds"] = round(time.time() - t0, 1)
    return finalize(report, out, ok)


def screen_has_menu(png):
    """True when GRUB's menu is on screen: its selected entry is a solid dark-blue bar."""
    from PIL import Image
    im = Image.open(png).convert("RGB")
    w, h = im.size
    small = im.resize((max(1, w // 4), max(1, h // 4)))
    blue = sum(1 for r, g, b in small.get_flattened_data() if b > 120 and r < 60 and g < 60)
    return blue > (small.size[0] * small.size[1]) * 0.003


def finalize(report, out, ok):
    report["result"] = "pass" if ok and all(c["pass"] for c in report["checks"].values()) else "fail"
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(report, f, indent=2)
    print(f"{report['scenario']}: {report['result'].upper()} ({out}/report.json)")
    return 0 if report["result"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
