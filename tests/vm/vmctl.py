#!/usr/bin/env python3
"""vmctl - step-by-step control of a detached Ingot test VM (interactive validation).

  vmctl.py start NAME --arch amd64 [--iso X] [--disk X.qcow2 --disk-size 40G] [--memory 4096] [--secureboot]
  vmctl.py key NAME KEY [KEY...]          one chord, e.g.  key NAME ctrl alt t
  vmctl.py keys NAME KEY KEY ...          a sequence of single keys
  vmctl.py type NAME "text"               type text (US layout)
  vmctl.py shot NAME [FILE.png]           screenshot
  vmctl.py click NAME X Y [--abs-w W --abs-h H]   absolute pointer click (tablet device)
  vmctl.py serial NAME [N]                last N lines of the serial log
  vmctl.py run NAME "cmd" [--timeout S]   run on a logged-in serial shell
  vmctl.py eject NAME                     remove the ISO
  vmctl.py stop NAME

State lives in tests/vm/results/<NAME>/.
"""
import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingotvm import FIRMWARE  # noqa: E402

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def d(name):
    return os.path.join(RESULTS, name)


class QMP:
    def __init__(self, name):
        self.s = socket.socket(socket.AF_UNIX)
        self.s.settimeout(30)
        self.s.connect(os.path.join(d(name), "qmp.sock"))
        self.f = self.s.makefile("rwb")
        self._read()
        self.cmd("qmp_capabilities")

    def _read(self):
        while True:
            m = json.loads(self.f.readline())
            if "event" not in m:
                return m

    def cmd(self, execute, **args):
        self.f.write(json.dumps({"execute": execute, "arguments": args}).encode() + b"\n")
        self.f.flush()
        r = self._read()
        if "error" in r:
            raise SystemExit(f"QMP error: {r['error']}")
        return r.get("return")


def start(a):
    wd = d(a.name)
    os.makedirs(wd, exist_ok=True)
    fw = FIRMWARE[a.arch]
    vars_path = os.path.join(wd, "vars.fd")
    if not os.path.exists(vars_path):
        shutil.copy(fw["vars_sb"] if a.secureboot else fw["vars"], vars_path)
    code = fw["code_sb"] if a.secureboot else fw["code"]
    if a.disk and not os.path.exists(a.disk):
        subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", a.disk, a.disk_size], check=True)
    if a.arch == "amd64":
        cmd = ["qemu-system-x86_64", "-machine", "q35,smm=on" if a.secureboot else "q35", "-accel", "kvm",
               "-cpu", "host", "-device", "virtio-vga"]
        if a.secureboot:
            cmd += ["-global", "driver=cfi.pflash01,property=secure,value=on"]
        if a.iso:
            cmd += ["-drive", f"file={a.iso},media=cdrom,if=none,id=cd0,readonly=on", "-device", "ide-cd,drive=cd0,bootindex=1"]
    else:
        tcg = os.uname().machine != "aarch64"
        cmd = ["qemu-system-aarch64", "-machine", "virt,gic-version=3",
               # "-cpu max" makes AAVMF crawl under TCG; Neoverse-N1 (ARMv8.2) is enough for Ubuntu.
               *(["-accel", "tcg,thread=multi", "-cpu", "neoverse-n1"] if tcg else ["-accel", "kvm", "-cpu", "host"]),
               "-device", "virtio-gpu-pci", "-device", "qemu-xhci", "-device", "usb-kbd"]
        if a.iso:
            cmd += ["-device", "virtio-scsi-pci,id=scsi0", "-drive", f"file={a.iso},media=cdrom,if=none,id=cd0,readonly=on",
                    "-device", "scsi-cd,drive=cd0,bootindex=1"]
    cmd += ["-m", str(a.memory), "-smp", str(a.cpus),
            "-drive", f"if=pflash,format=raw,unit=0,readonly=on,file={code}",
            "-drive", f"if=pflash,format=raw,unit=1,file={vars_path}",
            "-display", "none", "-device", "virtio-rng-pci", "-device", "usb-ehci" if a.arch == "amd64" else "virtio-tablet-pci",
            "-qmp", f"unix:{wd}/qmp.sock,server=on,wait=off",
            "-chardev", f"socket,id=ser0,path={wd}/serial.sock,server=on,wait=off,logfile={wd}/serial.log,logappend=on",
            "-serial", "chardev:ser0",
            "-netdev", "user,id=n0", "-device", "virtio-net-pci,netdev=n0"]
    if a.arch == "amd64":
        cmd += ["-device", "usb-tablet"]
    if a.disk:
        cmd += ["-drive", f"file={os.path.abspath(a.disk)},if=none,id=hd0,format=qcow2,cache=unsafe",
                "-device", "virtio-blk-pci,drive=hd0,bootindex=2"]
    with open(os.path.join(wd, "qemu.cmd"), "w") as f:
        f.write(" ".join(cmd) + "\n")
    p = subprocess.Popen(cmd, stdout=open(os.path.join(wd, "qemu.log"), "w"), stderr=subprocess.STDOUT,
                         start_new_session=True)
    with open(os.path.join(wd, "pid"), "w") as f:
        f.write(str(p.pid))
    for _ in range(100):
        if os.path.exists(os.path.join(wd, "qmp.sock")):
            break
        time.sleep(0.1)
    print(f"started {a.name} pid {p.pid}")


QCODES = {" ": "spc", "\n": "ret", "-": "minus", "=": "equal", ".": "dot", "/": "slash", ",": "comma",
          ";": "semicolon", "'": "apostrophe", "\\": "backslash", "\t": "tab", "`": "grave_accent",
          "[": "bracket_left", "]": "bracket_right"}
SHIFTED = {"_": "minus", ":": "semicolon", "|": "backslash", '"': "apostrophe", ">": "dot", "<": "comma",
           "&": "7", "*": "8", "(": "9", ")": "0", "$": "4", "!": "1", "@": "2", "~": "grave_accent",
           "+": "equal", "?": "slash", "#": "3", "%": "5", "^": "6", "{": "bracket_left", "}": "bracket_right"}


def send_keys(q, keys, hold=90):
    q.cmd("send-key", keys=[{"type": "qcode", "data": k} for k in keys], **{"hold-time": hold})
    time.sleep(0.14)  # faster typing drops keys in Qt/GTK under QEMU


def type_text(q, text):
    for ch in text:
        if ch in QCODES:
            send_keys(q, [QCODES[ch]])
        elif ch in SHIFTED:
            send_keys(q, ["shift", SHIFTED[ch]])
        elif ch.isupper():
            send_keys(q, ["shift", ch.lower()])
        else:
            send_keys(q, [ch])


def click(q, x, y, w, h, button="left", double=False):
    ax, ay = int(x * 32767 / w), int(y * 32767 / h)
    q.cmd("input-send-event", events=[{"type": "abs", "data": {"axis": "x", "value": ax}},
                                      {"type": "abs", "data": {"axis": "y", "value": ay}}])
    time.sleep(0.05)
    for _ in range(2 if double else 1):
        for down in (True, False):
            q.cmd("input-send-event", events=[{"type": "btn", "data": {"down": down, "button": button}}])
            time.sleep(0.06)


def serial_run(name, cmd, timeout):
    """Run a command on the logged-in serial shell, reading the reply from the socket
    (QEMU's chardev logfile can lag behind)."""
    marker = f"__VMCTL_{int(time.time() * 1000)}__"
    s = socket.socket(socket.AF_UNIX)
    s.connect(os.path.join(d(name), "serial.sock"))
    s.settimeout(0.5)
    s.sendall(f"{cmd}; echo {marker} $?\n".encode())
    buf = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            chunk = s.recv(65536)
            if chunk:
                buf += chunk
        except socket.timeout:
            pass
        data = buf.decode("utf-8", "replace")
        m = re.search(rf"{marker} (\d+)", data)
        if m:
            s.close()
            out = re.sub(r"\x1b\][^\x07\x1b]*(\x07|\x1b\\)", "", data[:m.start()])
            out = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", out).replace("\r", "")
            out = "\n".join(ln for ln in out.split("\n") if f"echo {marker}" not in ln)
            print(out.strip())
            return int(m.group(1))
    s.close()
    print(buf.decode("utf-8", "replace")[-3000:])
    raise SystemExit(f"timeout after {timeout}s")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("start")
    p.add_argument("name")
    p.add_argument("--arch", default="amd64")
    p.add_argument("--iso")
    p.add_argument("--disk")
    p.add_argument("--disk-size", default="40G")
    p.add_argument("--memory", type=int, default=4096)
    p.add_argument("--cpus", type=int, default=4)
    p.add_argument("--secureboot", action="store_true")
    for c in ("key", "keys"):
        p = sub.add_parser(c)
        p.add_argument("name")
        p.add_argument("k", nargs="+")
    p = sub.add_parser("type")
    p.add_argument("name")
    p.add_argument("text")
    p = sub.add_parser("shot")
    p.add_argument("name")
    p.add_argument("file", nargs="?")
    p = sub.add_parser("click")
    p.add_argument("name")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.add_argument("--abs-w", type=int, default=1280)
    p.add_argument("--abs-h", type=int, default=800)
    p.add_argument("--double", action="store_true")
    p.add_argument("--right", action="store_true")
    p = sub.add_parser("serial")
    p.add_argument("name")
    p.add_argument("n", nargs="?", type=int, default=40)
    p = sub.add_parser("run")
    p.add_argument("name")
    p.add_argument("command")
    p.add_argument("--timeout", type=int, default=120)
    for c in ("stop", "eject"):
        p = sub.add_parser(c)
        p.add_argument("name")
    a = ap.parse_args()

    if a.cmd == "start":
        return start(a)
    if a.cmd == "serial":
        with open(os.path.join(d(a.name), "serial.log"), "rb") as f:
            text = f.read().decode("utf-8", "replace")
        text = re.sub(r"\x1b\][^\x07\x1b]*(\x07|\x1b\\)", "", text)
        print("\n".join(re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", text).replace("\r", "").split("\n")[-a.n:]))
        return 0
    if a.cmd == "run":
        return serial_run(a.name, a.command, a.timeout)
    q = QMP(a.name)
    if a.cmd == "key":
        send_keys(q, a.k)
    elif a.cmd == "keys":
        for k in a.k:
            send_keys(q, [k])
            time.sleep(0.15)
    elif a.cmd == "type":
        type_text(q, a.text)
    elif a.cmd == "shot":
        path = os.path.abspath(a.file or os.path.join(d(a.name), f"shot-{int(time.time())}.png"))
        q.cmd("screendump", filename=path, format="png")
        print(path)
    elif a.cmd == "click":
        click(q, a.x, a.y, a.abs_w, a.abs_h, "right" if a.right else "left", a.double)
    elif a.cmd == "eject":
        q.cmd("eject", device="cd0", force=True)
    elif a.cmd == "stop":
        try:
            q.cmd("quit")
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
