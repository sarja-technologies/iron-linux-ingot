"""VM backend: QEMU with KVM (when available) for the strongest isolation.

The agent runs its own kernel. QEMU itself runs as the unprivileged
`iron-agent-vm` system user inside a hardened transient unit whose cgroup
limits cover guest RAM plus a fixed emulator overhead. Storage is a qcow2
overlay (virtual size = storage limit) on the shared read-only base image.
"""
import grp
import json
import os
import pwd
import socket
import subprocess
import time

from . import approvals, storage, units
from .config import RUN_DIR, ConfigError

VM_USER = "iron-agent-vm"
QEMU_OVERHEAD_MIB = 384
DISPLAY_SIZE = (1600, 900)


def run_dir(agent):
    return os.path.join(RUN_DIR, agent.id)


def _vm_ids():
    try:
        pw = pwd.getpwnam(VM_USER)
        return pw.pw_uid, pw.pw_gid
    except KeyError:
        raise ConfigError(f"system user {VM_USER} missing (reinstall iron-agent-desktops)")


def prepare_run_dir(agent):
    uid, gid = _vm_ids()
    d = run_dir(agent)
    os.makedirs(RUN_DIR, mode=0o711, exist_ok=True)
    os.makedirs(d, exist_ok=True)
    os.chown(d, agent.owner_uid, gid)
    os.chmod(d, 0o750)
    # vm/ holds QEMU's own sockets and console log (QEMU runs as iron-agent-vm).
    for sub, mode in (("display", 0o755), ("control", 0o755), ("control/inbox", 0o750),
                      ("control/requests", 0o1733), ("control/responses", 0o755), ("vm", 0o750)):
        p = os.path.join(d, sub)
        os.makedirs(p, exist_ok=True)
        os.chown(p, uid, gid)
        os.chmod(p, mode)
    try:  # a shutdown request the previous run never consumed
        os.unlink(os.path.join(d, "control", "shutdown"))
    except FileNotFoundError:
        pass
    return d


def ensure_disk(store, agent):
    disk = store.path(agent.id, "disk.qcow2")
    if not os.path.exists(disk):
        storage.create_vm_disk(disk, agent.image, agent.resources.storage_gib)
    uid, gid = _vm_ids()
    os.chown(disk, uid, gid)
    os.chown(store.path(agent.id), 0, gid)
    os.chmod(store.path(agent.id), 0o750)
    return disk


def _kvm_group():
    """The group that owns /dev/kvm (kvm on most systems, render on some udev setups).
    DevicePolicy=closed still limits the unit to /dev/kvm alone."""
    try:
        return grp.getgrgid(os.stat("/dev/kvm").st_gid).gr_name
    except (OSError, KeyError):
        return "kvm"


def qemu_command(agent, disk, host):
    r = agent.resources
    img = storage.image_paths(agent.image)
    rd = run_dir(agent)
    kvm = host.kvm and os.access("/dev/kvm", os.R_OK)
    arch = os.uname().machine
    # The guest's Xorg draws on this virtual GPU; QEMU exports it as VNC. A USB
    # tablet gives absolute pointer positions, so the host viewer's pointer
    # lines up with the guest's.
    xres, yres = DISPLAY_SIZE
    if arch == "x86_64":
        cmd = ["qemu-system-x86_64", "-machine", "q35", "-device", f"virtio-vga,xres={xres},yres={yres}",
               "-device", "qemu-xhci", "-device", "usb-tablet"]
        console = "ttyS0"
    else:
        cmd = ["qemu-system-aarch64", "-machine", "virt,gic-version=max",
               "-device", f"virtio-gpu-pci,xres={xres},yres={yres}",
               "-device", "qemu-xhci", "-device", "usb-kbd", "-device", "usb-tablet"]
        console = "ttyAMA0"
    cmd += ["-accel", "kvm", "-cpu", "host"] if kvm else ["-accel", "tcg,thread=multi", "-cpu", "max"]
    cmd += [
        "-name", f"iron-agent-{agent.id},process=iron-agent-{agent.id}",
        "-smp", str(r.cpu_threads), "-m", f"{r.memory_mib}M",
        "-kernel", img["kernel"], "-initrd", img["initrd"],
        "-append", f"root=/dev/vda rw console={console} quiet iron.agent=1",
        "-drive", f"file={disk},if=virtio,format=qcow2,discard=unmap,cache=none",
        "-virtfs", f"local,path={rd}/control,mount_tag=ironctl,security_model=mapped-xattr",
        "-vnc", f"unix:{rd}/display/vnc.sock",
        "-qmp", f"unix:{rd}/vm/qmp.sock,server=on,wait=off",
        "-serial", f"file:{rd}/vm/console.log",
        "-device", "virtio-rng-pci", "-device", "virtio-balloon-pci",
        "-display", "none", "-nodefaults", "-no-user-config",
        "-sandbox", "on,obsolete=deny,elevateprivileges=deny,spawn=deny,resourcecontrol=deny",
    ]
    restrict = "on" if r.network == "none" else "off"
    cmd += ["-netdev", f"user,id=n0,restrict={restrict}", "-device", "virtio-net-pci,netdev=n0"]
    return cmd, kvm


def start(store, agent, host):
    if agent.resources.gpu == "shared":
        raise ConfigError("GPU access for VM agents is not available yet (container agents only)")
    if agent.shares:
        # QEMU runs as an unprivileged system user that cannot read 0750 home
        # directories; sharing into VMs needs virtiofsd with ID mapping (planned).
        raise ConfigError("shared folders are supported for container agents; VM agents exchange "
                          "files through their outbox")
    disk = ensure_disk(store, agent)
    prepare_run_dir(agent)
    cmd, kvm = qemu_command(agent, disk, host)
    props = units.cgroup_properties(agent.resources, host.threads, extra_memory_mib=QEMU_OVERHEAD_MIB)
    props += [f"User={VM_USER}", f"Group={VM_USER}", f"SupplementaryGroups={_kvm_group()}",
              "NoNewPrivileges=yes", "ProtectSystem=strict", "ProtectHome=yes", "PrivateTmp=yes",
              f"ReadWritePaths={store.path(agent.id)} {run_dir(agent)}",
              "ProtectKernelTunables=yes", "ProtectKernelModules=yes", "ProtectControlGroups=yes",
              "RestrictNamespaces=yes", "LockPersonality=yes", "UMask=0002",
              "DevicePolicy=closed", "DeviceAllow=/dev/kvm rw", "DeviceAllow=/dev/net/tun rw",
              "KillMode=mixed", "TimeoutStopSec=30"]
    units.systemd_run(agent.id, cmd, props, description=f"Iron Agent Desktop (VM): {agent.name}")
    return {"kvm": kvm}


class QMP:
    def __init__(self, path, timeout=10):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(timeout)
        deadline = time.time() + timeout
        while True:
            try:
                self.sock.connect(path)
                break
            except OSError:
                if time.time() > deadline:
                    raise ConfigError("VM control socket unavailable")
                time.sleep(0.2)
        self.f = self.sock.makefile("rwb")
        self._read()
        self.cmd("qmp_capabilities")

    def _read(self):
        while True:
            msg = json.loads(self.f.readline())
            if "event" not in msg:
                return msg

    def cmd(self, execute, **arguments):
        self.f.write(json.dumps({"execute": execute, "arguments": arguments}).encode() + b"\n")
        self.f.flush()
        r = self._read()
        if "error" in r:
            raise ConfigError(r["error"].get("desc", "QMP error"))
        return r.get("return")

    def hmp(self, line):
        return self.cmd("human-monitor-command", **{"command-line": line})

    def close(self):
        self.sock.close()


def _qmp(agent):
    return QMP(os.path.join(run_dir(agent), "vm", "qmp.sock"))


def pause(agent):
    q = _qmp(agent)
    q.cmd("stop")
    q.close()


def resume(agent):
    q = _qmp(agent)
    q.cmd("cont")
    q.close()


def stop(agent, timeout=30):
    # Ask the guest's runner (root in the guest) over the control share; the
    # minimal agent image has no ACPI power-button handling, so system_powerdown
    # alone is ignored and the VM would only stop by SIGTERM after the timeout.
    # Host-written like approval responses: the guest sees it as root-owned,
    # which the agent user cannot forge.
    try:
        approvals.write_host_file(os.path.join(run_dir(agent), "control"), "shutdown", "poweroff\n",
                                  virtfs_root=True)
    except OSError:
        pass
    try:
        q = _qmp(agent)
        q.cmd("system_powerdown")
        q.close()
    except (ConfigError, OSError):
        pass
    deadline = time.time() + timeout
    while time.time() < deadline:
        if units.unit_state(agent.id)["active"] in ("inactive", "failed", ""):
            return
        time.sleep(0.5)
    units.stop(agent.id)


def snapshot(store, agent, name):
    """Live snapshot (disk + RAM) while running; disk-only when stopped."""
    if units.unit_state(agent.id)["active"] == "active":
        q = _qmp(agent)
        out = q.hmp(f"savevm {name}")
        q.close()
        if out and "error" in out.lower():
            raise ConfigError(out.strip())
    else:
        storage.run(["qemu-img", "snapshot", "-c", name, store.path(agent.id, "disk.qcow2")])


def restore(store, agent, name):
    if units.unit_state(agent.id)["active"] == "active":
        q = _qmp(agent)
        out = q.hmp(f"loadvm {name}")
        q.close()
        if out and "error" in out.lower():
            raise ConfigError(out.strip())
    else:
        storage.run(["qemu-img", "snapshot", "-a", name, store.path(agent.id, "disk.qcow2")])


def share_display(agent):
    """QEMU (running as iron-agent-vm) creates the VNC socket; let the agent's
    owner connect to it — and nobody else (its parent dirs are owner-only)."""
    sock = os.path.join(run_dir(agent), "display", "vnc.sock")
    try:
        st = os.stat(sock)
    except FileNotFoundError:
        return False
    owner_gid = pwd.getpwuid(agent.owner_uid).pw_gid
    if st.st_gid != owner_gid or (st.st_mode & 0o070) != 0o060:
        os.chown(sock, -1, owner_gid)
        os.chmod(sock, 0o660)
    return True


def guest_console_log(agent):
    try:
        with open(os.path.join(run_dir(agent), "vm", "console.log"), errors="replace") as f:
            return f.read()[-20000:]
    except OSError:
        return ""
