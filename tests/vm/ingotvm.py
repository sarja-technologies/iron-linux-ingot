"""ingotvm - drive Iron Linux Ingot images in QEMU for automated validation.

Controls a QEMU guest over QMP (keys, screenshots, power) and a serial console
socket (log capture, shell commands). Used by tests/vm/*.py scenarios.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import time

FIRMWARE = {
    "amd64": {
        "code": "/usr/share/OVMF/OVMF_CODE_4M.fd",
        "vars": "/usr/share/OVMF/OVMF_VARS_4M.fd",
        "code_sb": "/usr/share/OVMF/OVMF_CODE_4M.secboot.fd",
        "vars_sb": "/usr/share/OVMF/OVMF_VARS_4M.ms.fd",
    },
    "arm64": {
        "code": "/usr/share/AAVMF/AAVMF_CODE.no-secboot.fd",
        "vars": "/usr/share/AAVMF/AAVMF_VARS.fd",
        "code_sb": "/usr/share/AAVMF/AAVMF_CODE.secboot.fd",
        "vars_sb": "/usr/share/AAVMF/AAVMF_VARS.ms.fd",
    },
}


class VM:
    def __init__(self, arch, workdir, iso=None, disk=None, memory=4096, cpus=4,
                 secureboot=False, net=True, extra=None, name="ingot"):
        self.arch = arch
        self.workdir = os.path.abspath(workdir)
        os.makedirs(self.workdir, exist_ok=True)
        self.iso, self.disk = iso, disk
        self.memory, self.cpus = memory, cpus
        self.secureboot = secureboot
        self.net = net
        self.extra = extra or []
        self.name = name
        self.qmp_path = os.path.join(self.workdir, f"{name}.qmp")
        self.serial_path = os.path.join(self.workdir, f"{name}.serial")
        self.serial_log_path = os.path.join(self.workdir, f"{name}-serial.log")
        self.proc = None
        self._qmp = None
        self._serial = None
        self._buf = b""
        self._log = None

    # ---- lifecycle -----------------------------------------------------
    def command(self):
        fw = FIRMWARE[self.arch]
        code = fw["code_sb"] if self.secureboot else fw["code"]
        vars_src = fw["vars_sb"] if self.secureboot else fw["vars"]
        vars_path = os.path.join(self.workdir, f"{self.name}-vars.fd")
        if not os.path.exists(vars_path):
            shutil.copy(vars_src, vars_path)
        if self.arch == "amd64":
            cmd = ["qemu-system-x86_64", "-machine", "q35,smm=on" if self.secureboot else "q35",
                   "-accel", "kvm", "-cpu", "host"]
            if self.secureboot:
                cmd += ["-global", "driver=cfi.pflash01,property=secure,value=on"]
            cmd += ["-device", "virtio-vga"]
            cdrom = ["-drive", f"file={self.iso},media=cdrom,if=none,id=cd0,readonly=on",
                     "-device", "ide-cd,drive=cd0,bootindex=1"] if self.iso else []
        else:
            accel = ["-accel", "kvm", "-cpu", "host"] if os.uname().machine == "aarch64" \
                else ["-accel", "tcg,thread=multi", "-cpu", "neoverse-n1"]  # "max" makes AAVMF crawl under TCG
            cmd = ["qemu-system-aarch64", "-machine", "virt,gic-version=3"] + accel
            cmd += ["-device", "virtio-gpu-pci", "-device", "qemu-xhci",
                    "-device", "usb-kbd", "-device", "usb-tablet"]
            cdrom = ["-device", "virtio-scsi-pci,id=scsi0",
                     "-drive", f"file={self.iso},media=cdrom,if=none,id=cd0,readonly=on",
                     "-device", "scsi-cd,drive=cd0,bootindex=1"] if self.iso else []
        cmd += ["-m", str(self.memory), "-smp", str(self.cpus),
                "-drive", f"if=pflash,format=raw,unit=0,readonly=on,file={code}",
                "-drive", f"if=pflash,format=raw,unit=1,file={vars_path}",
                "-display", "none",
                "-qmp", f"unix:{self.qmp_path},server=on,wait=off",
                "-serial", f"unix:{self.serial_path},server=on,wait=off",
                "-device", "virtio-rng-pci"]
        cmd += cdrom
        if self.disk:
            cmd += ["-drive", f"file={self.disk},if=none,id=hd0,format=qcow2,cache=unsafe",
                    "-device", "virtio-blk-pci,drive=hd0,bootindex=2"]
        if self.net:
            cmd += ["-netdev", "user,id=n0", "-device", "virtio-net-pci,netdev=n0"]
        else:
            cmd += ["-nic", "none"]
        return cmd + self.extra

    def start(self):
        for p in (self.qmp_path, self.serial_path):
            if os.path.exists(p):
                os.unlink(p)
        cmd = self.command()
        with open(os.path.join(self.workdir, f"{self.name}-qemu.cmd"), "w") as f:
            f.write(" ".join(cmd) + "\n")
        self.proc = subprocess.Popen(cmd, stdout=open(os.path.join(self.workdir, f"{self.name}-qemu.log"), "w"),
                                     stderr=subprocess.STDOUT)
        deadline = time.time() + 30
        while time.time() < deadline and not (os.path.exists(self.qmp_path) and os.path.exists(self.serial_path)):
            if self.proc.poll() is not None:
                raise RuntimeError(f"qemu exited: see {self.workdir}/{self.name}-qemu.log")
            time.sleep(0.2)
        self._qmp = socket.socket(socket.AF_UNIX)
        self._qmp.connect(self.qmp_path)
        self._qmp_file = self._qmp.makefile("rwb")
        self._qmp_read()  # greeting
        self.qmp("qmp_capabilities")
        self._serial = socket.socket(socket.AF_UNIX)
        self._serial.connect(self.serial_path)
        self._serial.setblocking(False)
        self._log = open(self.serial_log_path, "ab")
        return self

    def stop(self):
        try:
            if self.proc and self.proc.poll() is None:
                self.qmp("quit")
        except OSError:
            pass
        if self.proc:
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        for s in (self._qmp, self._serial):
            if s:
                s.close()
        if self._log:
            self._log.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    def alive(self):
        return self.proc and self.proc.poll() is None

    # ---- QMP -----------------------------------------------------------
    def _qmp_read(self):
        while True:
            line = self._qmp_file.readline()
            if not line:
                raise RuntimeError("QMP closed")
            msg = json.loads(line)
            if "event" in msg:
                continue
            return msg

    def qmp(self, execute, **args):
        self._qmp_file.write(json.dumps({"execute": execute, "arguments": args}).encode() + b"\n")
        self._qmp_file.flush()
        return self._qmp_read()

    def screendump(self, path):
        path = os.path.abspath(path)
        r = self.qmp("screendump", filename=path, format="png")
        if "error" in r:
            raise RuntimeError(r["error"])
        return path

    def key(self, *keys, hold_ms=80):
        """Press a chord, e.g. key('ctrl', 'alt', 'f2') or key('down')."""
        self.qmp("send-key", keys=[{"type": "qcode", "data": k} for k in keys], **{"hold-time": hold_ms})
        time.sleep(0.15)

    def type_text(self, text):
        special = {" ": "spc", "\n": "ret", "-": "minus", "=": "equal", ".": "dot", "/": "slash",
                   ",": "comma", ";": "semicolon", "'": "apostrophe", "_": ("shift", "minus"),
                   ":": ("shift", "semicolon"), "|": ("shift", "backslash"), "\\": "backslash",
                   "\"": ("shift", "apostrophe"), ">": ("shift", "dot"), "<": ("shift", "comma"),
                   "&": ("shift", "7"), "*": ("shift", "8"), "(": ("shift", "9"), ")": ("shift", "0"),
                   "$": ("shift", "4"), "!": ("shift", "1"), "@": ("shift", "2"), "~": ("shift", "grave_accent"),
                   "+": ("shift", "equal")}
        for ch in text:
            if ch in special:
                k = special[ch]
                self.key(*k) if isinstance(k, tuple) else self.key(k)
            elif ch.isupper():
                self.key("shift", ch.lower())
            else:
                self.key(ch)

    def powerdown(self):
        self.qmp("system_powerdown")

    # ---- serial ----------------------------------------------------------
    def _pump(self):
        try:
            while True:
                data = self._serial.recv(65536)
                if not data:
                    break
                self._buf += data
                self._log.write(data)
                self._log.flush()
        except BlockingIOError:
            pass

    def wait_serial(self, pattern, timeout=300, start=0):
        """Wait until regex `pattern` appears in the serial output; returns the match."""
        rx = re.compile(pattern.encode() if isinstance(pattern, str) else pattern)
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._pump()
            m = rx.search(self._buf, start)
            if m:
                return m
            if not self.alive():
                raise RuntimeError("VM exited while waiting for " + str(pattern))
            time.sleep(0.5)
        raise TimeoutError(f"timeout waiting for {pattern!r}")

    def serial_text(self):
        self._pump()
        return self._buf.decode("utf-8", "replace")

    def send_serial(self, text):
        self._serial.setblocking(True)
        self._serial.sendall(text.encode())
        self._serial.setblocking(False)

    def run(self, cmd, timeout=120):
        """Run a shell command on a logged-in serial shell; returns (rc, output)."""
        marker = f"__IRON_{int(time.time() * 1000)}__"
        start = len(self._buf)
        self.send_serial(f"{cmd}; echo {marker} $?\n")
        # The echoed command contains "<marker> $?", so only a digit status matches.
        m = self.wait_serial(rf"{marker} (\d+)", timeout=timeout, start=start)
        out = self._buf[start:m.start()].decode("utf-8", "replace")
        out = re.sub(r"\x1b\][^\x07\x1b]*(\x07|\x1b\\)", "", out)  # OSC (e.g. systemd 3008 context)
        out = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", out).replace("\r", "")
        # Drop the echoed command line (if the tty still echoes) and the prompt.
        lines = [ln for ln in out.split("\n") if f"echo {marker}" not in ln]
        while lines and lines[0].strip() in ("$", ""):
            lines.pop(0)
        if lines and lines[0].startswith("$ "):
            lines[0] = lines[0][2:]
        return int(m.group(1)), "\n".join(lines).strip("\n") + "\n"
