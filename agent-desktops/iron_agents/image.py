"""Build the Agent Desktop base image (run as root: `iron-agent image build`).

One Ubuntu rootfs (same release and arch as the host) serves both backends:
  rootfs/      used directly by container agents (copied into each agent disk)
  disk.qcow2   the same tree as an ext4 VM disk (VM agents)
  vmlinuz, initrd.img   for direct kernel boot of VM agents
"""
import json
import os
import shutil
import subprocess
import time

from .config import IMAGE_DIR

GUEST_PACKAGES = [
    "systemd-sysv", "dbus", "dbus-x11", "ca-certificates", "locales", "tzdata",
    "tigervnc-standalone-server", "openbox", "tint2", "xterm", "x11-xserver-utils", "xwallpaper",
    "fonts-inter", "fonts-hack", "fonts-dejavu-core",
    "python3", "git", "curl", "wget", "less", "nano", "unzip", "zstd", "jq", "ripgrep",
    "iproute2", "iputils-ping", "openssh-client", "xdg-utils", "xclip",
]
# VM agents draw on their own virtual screen: a real X server instead of Xvnc.
VM_PACKAGES = ["linux-image-virtual", "initramfs-tools", "e2fsprogs",
               "xserver-xorg-core", "xserver-xorg-input-libinput", "xauth"]
NODE_PACKAGES = ["nodejs", "npm"]
GUEST_FILES = "/usr/share/iron-agents/guest"
RUNTIMES = "/usr/share/iron-agents/runtimes"


def sh(cmd, **kw):
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def chroot(root, *cmd, env=None):
    e = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "DEBIAN_FRONTEND": "noninteractive", "LC_ALL": "C.UTF-8"}
    e.update(env or {})
    sh(["chroot", root, *cmd], env=e)


def _host_release():
    rel = {}
    with open("/etc/os-release") as f:
        for line in f:
            k, _, v = line.strip().partition("=")
            rel[k] = v.strip('"')
    return rel.get("UBUNTU_CODENAME") or rel.get("VERSION_CODENAME") or "resolute"


def _mirror(arch):
    return "http://archive.ubuntu.com/ubuntu" if arch == "amd64" else "http://ports.ubuntu.com/ubuntu-ports"


class Mounts:
    def __init__(self, root):
        self.root, self.done = root, []

    def __enter__(self):
        for src, dst, args in (("proc", "proc", ["-t", "proc"]), ("sysfs", "sys", ["-t", "sysfs"]),
                               ("/dev", "dev", ["--bind"]), ("devpts", "dev/pts", ["-t", "devpts"])):
            p = os.path.join(self.root, dst)
            os.makedirs(p, exist_ok=True)
            sh(["mount", *args, src, p])
            self.done.append(p)
        return self

    def __exit__(self, *exc):
        for p in reversed(self.done):
            subprocess.run(["umount", "-l", p])


def build(name="base", vm=False, runtimes=(), browser=False, mirror=None):
    arch = subprocess.run(["dpkg", "--print-architecture"], capture_output=True, text=True).stdout.strip()
    suite = _host_release()
    mirror = mirror or _mirror(arch)
    dest = os.path.join(IMAGE_DIR, name)
    work = dest + ".building"
    if os.path.exists(work):
        shutil.rmtree(work)
    root = os.path.join(work, "rootfs")
    os.makedirs(work, mode=0o755)
    t0 = time.time()
    sh(["debootstrap", "--variant=minbase", "--components=main,universe", suite, root, mirror])
    with open(os.path.join(root, "etc/apt/sources.list"), "w") as f:
        f.write(f"deb {mirror} {suite} main universe\ndeb {mirror} {suite}-updates main universe\n"
                f"deb {mirror} {suite}-security main universe\n")
    shutil.copy("/etc/resolv.conf", os.path.join(root, "etc/resolv.conf"))
    pkgs = GUEST_PACKAGES + (VM_PACKAGES if vm else []) + (NODE_PACKAGES if runtimes else [])
    with Mounts(root):
        chroot(root, "apt-get", "update")
        with open(os.path.join(root, "usr/sbin/policy-rc.d"), "w") as f:
            f.write("#!/bin/sh\nexit 101\n")
        os.chmod(os.path.join(root, "usr/sbin/policy-rc.d"), 0o755)
        chroot(root, "apt-get", "install", "-y", "--no-install-recommends", *pkgs)
        if browser:
            _install_firefox(root)
        chroot(root, "useradd", "-m", "-u", "1000", "-s", "/bin/bash", "-c", "Agent", "agent")
        chroot(root, "passwd", "-l", "root")
        _install_guest_files(root)
        for rid in runtimes:
            with open(os.path.join(RUNTIMES, f"{rid}.json")) as f:
                spec = json.load(f)
            if spec.get("install"):
                chroot(root, *spec["install"])
        chroot(root, "systemctl", "enable", "iron-agent-display.service", "iron-agent-runner.service",
               "iron-agent-vm-setup.service", *(["iron-agent-display-vm.service"] if vm else []))
        chroot(root, "systemctl", "mask", "systemd-networkd-wait-online.service", "getty@tty1.service")
        os.unlink(os.path.join(root, "usr/sbin/policy-rc.d"))
        chroot(root, "apt-get", "clean")
    with open(os.path.join(root, "etc/hostname"), "w") as f:
        f.write("iron-agent\n")
    open(os.path.join(root, "etc/machine-id"), "w").close()

    if vm:
        _build_vm_disk(root, work)
    info = {"name": name, "arch": arch, "suite": suite, "built": time.time(), "vm": vm,
            "runtimes": list(runtimes), "browser": browser, "seconds": round(time.time() - t0)}
    with open(os.path.join(work, "image.json"), "w") as f:
        json.dump(info, f, indent=2)
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.rename(work, dest)
    print(f"agent image '{name}' ready in {dest} ({info['seconds']}s)")
    return info


def _install_firefox(root):
    shutil.copy("/usr/share/keyrings/packages.mozilla.org.gpg", os.path.join(root, "usr/share/keyrings/"))
    shutil.copy("/etc/apt/sources.list.d/mozilla.sources", os.path.join(root, "etc/apt/sources.list.d/"))
    shutil.copy("/etc/apt/preferences.d/mozilla.pref", os.path.join(root, "etc/apt/preferences.d/"))
    chroot(root, "apt-get", "update")
    chroot(root, "apt-get", "install", "-y", "--no-install-recommends", "firefox")


def _install_guest_files(root):
    g = GUEST_FILES
    os.makedirs(os.path.join(root, "usr/lib/iron-agent"), exist_ok=True)
    for f in ("iron-agent-runner", "iron-agent-session", "iron-agent-vm-setup", "iron-agent-display-vm"):
        shutil.copy(os.path.join(g, f), os.path.join(root, "usr/lib/iron-agent", f))
    for f in ("iron-approve", "iron-elevate"):
        shutil.copy(os.path.join(g, f), os.path.join(root, "usr/bin", f))
    for f in os.listdir(os.path.join(g, "units")):
        shutil.copy(os.path.join(g, "units", f), os.path.join(root, "etc/systemd/system", f))
    os.makedirs(os.path.join(root, "usr/share/iron-agents"), exist_ok=True)
    shutil.copytree(RUNTIMES, os.path.join(root, "usr/share/iron-agents/runtimes"), dirs_exist_ok=True)
    os.makedirs(os.path.join(root, "etc/claude-code"), exist_ok=True)
    shutil.copy(os.path.join(g, "claude-managed-settings.json"), os.path.join(root, "etc/claude-code/managed-settings.json"))
    os.makedirs(os.path.join(root, "usr/share/iron-agent"), exist_ok=True)
    wp = "/usr/share/backgrounds/iron/ingot-forge.jpg"
    if os.path.exists(wp):
        shutil.copy(wp, os.path.join(root, "usr/share/iron-agent/wallpaper.png"))
    os.makedirs(os.path.join(root, "etc/iron-agent"), exist_ok=True)
    with open(os.path.join(root, "etc/iron-agent/runtime.json"), "w") as f:
        json.dump({"runtime": "shell"}, f)


def _build_vm_disk(root, work):
    kernels = sorted(f for f in os.listdir(os.path.join(root, "boot")) if f.startswith("vmlinuz-"))
    if not kernels:
        raise RuntimeError("VM image has no kernel")
    kver = kernels[-1][len("vmlinuz-"):]
    shutil.copy(os.path.join(root, "boot", f"vmlinuz-{kver}"), os.path.join(work, "vmlinuz"))
    shutil.copy(os.path.join(root, "boot", f"initrd.img-{kver}"), os.path.join(work, "initrd.img"))
    os.chmod(os.path.join(work, "vmlinuz"), 0o644)
    os.chmod(os.path.join(work, "initrd.img"), 0o644)
    raw = os.path.join(work, "disk.raw")
    with open(raw, "wb") as f:
        f.truncate(8 << 30)
    sh(["mkfs.ext4", "-q", "-F", "-L", "iron-agent", "-d", root, raw])
    sh(["qemu-img", "convert", "-q", "-O", "qcow2", "-c", raw, os.path.join(work, "disk.qcow2")])
    os.unlink(raw)
    os.chmod(os.path.join(work, "disk.qcow2"), 0o644)
