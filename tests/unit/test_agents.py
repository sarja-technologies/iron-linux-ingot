"""Unit tests for iron_agents (no root, no containers: pure logic and file safety)."""
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "agent-desktops"))
_tmp_state = tempfile.mkdtemp()
os.environ["IRON_AGENTS_STATE"] = _tmp_state

from iron_agents import approvals, outputs, rfb, units  # noqa: E402
from iron_agents.config import (ConfigError, GlobalConfig, HostResources, Resources,  # noqa: E402
                                preset_resources, validate_resources)
from iron_agents.container import allocate_uid_base, nspawn_command, validate_share_path  # noqa: E402
from iron_agents.model import Agent, Share, StateError, Store, new_id  # noqa: E402

HOST = HostResources(threads=16, memory_mib=32000, kvm=True, cgroup_v2=True, arch="x86_64",
                     render_nodes=["renderD128"])
GCFG = GlobalConfig()


class ConfigTests(unittest.TestCase):
    def test_presets_scale_with_host(self):
        light, bal, heavy = (preset_resources(p, HOST) for p in ("light", "balanced", "heavy"))
        self.assertEqual((light.cpu_threads, bal.cpu_threads, heavy.cpu_threads), (2, 4, 8))
        self.assertLess(light.memory_mib, bal.memory_mib)
        self.assertLess(bal.memory_mib, heavy.memory_mib)
        self.assertEqual(light.network, "none")
        self.assertEqual(heavy.gpu, "shared")

    def test_gpu_preset_dropped_without_render_node(self):
        h = HostResources(threads=4, memory_mib=8000, kvm=False, cgroup_v2=True, arch="aarch64")
        self.assertEqual(preset_resources("heavy", h).gpu, "none")

    def test_heavy_within_user_limits(self):
        _, needs_admin = validate_resources(preset_resources("heavy", HOST), HOST, GCFG)
        self.assertFalse(needs_admin)

    def test_beyond_half_needs_admin(self):
        r = Resources(cpu_threads=12, cpu_quota_percent=1200, memory_mib=20000)
        _, needs_admin = validate_resources(r, HOST, GCFG)
        self.assertTrue(needs_admin)
        _, needs_admin = validate_resources(r, HOST, GCFG, admin=True)
        self.assertFalse(needs_admin)

    def test_host_reserve_enforced(self):
        with self.assertRaises(ConfigError):
            validate_resources(Resources(memory_mib=31000), HOST, GCFG)

    def test_quota_bounded_by_threads(self):
        with self.assertRaises(ConfigError):
            validate_resources(Resources(cpu_threads=2, cpu_quota_percent=300), HOST, GCFG)

    def test_gpu_requires_render_node(self):
        h = HostResources(threads=8, memory_mib=16000, kvm=True, cgroup_v2=True, arch="x86_64")
        with self.assertRaises(ConfigError):
            validate_resources(Resources(gpu="shared"), h, GCFG)

    def test_global_config_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.conf")
            c = GlobalConfig(enabled=True, max_agents=5)
            c.save(p)
            c2 = GlobalConfig.load(p)
            self.assertTrue(c2.enabled)
            self.assertEqual(c2.max_agents, 5)

    def test_disabled_by_default(self):
        self.assertFalse(GlobalConfig.load("/nonexistent").enabled)


class UnitTests(unittest.TestCase):
    def test_cpuset_leaves_cpu0(self):
        self.assertEqual(units.cpuset(4, 16), "12-15")
        self.assertEqual(units.cpuset(1, 4), "3")
        self.assertEqual(units.cpuset(64, 8), "0-7")

    def test_cgroup_properties(self):
        r = Resources(cpu_threads=2, cpu_quota_percent=150, memory_mib=2048, max_runtime_minutes=30)
        p = units.cgroup_properties(r, 8, gpu_devices=["/dev/dri/renderD128"])
        self.assertIn("CPUQuota=150%", p)
        self.assertIn("MemoryMax=2048M", p)
        self.assertIn("MemorySwapMax=0", p)
        self.assertIn("RuntimeMaxSec=1800", p)
        self.assertIn("AllowedCPUs=6-7", p)
        self.assertIn("DeviceAllow=/dev/dri/renderD128 rw", p)


class ModelTests(unittest.TestCase):
    def test_transitions(self):
        a = Agent(id=new_id(), name="t", owner_uid=1000)
        a.transition("starting")
        a.transition("running")
        a.transition("paused")
        a.transition("finished", "time limit")
        with self.assertRaises(StateError):
            a.transition("paused")

    def test_roundtrip_and_store(self):
        s = Store(tempfile.mkdtemp())
        a = Agent(id=new_id(), name="Claude coding", owner_uid=1000, shares=[Share("/home/u/p", True, "p")])
        s.save(a)
        b = s.load_all()[a.id]
        self.assertEqual(b.shares[0].host_path, "/home/u/p")
        self.assertEqual(b.resources.memory_mib, a.resources.memory_mib)

    def test_bad_ids_rejected(self):
        s = Store(tempfile.mkdtemp())
        for bad in ("../etc", "a/../../x", "", "A0123456789"):
            with self.assertRaises(ConfigError):
                s.path(bad)

    def test_name_validation(self):
        with self.assertRaises(ConfigError):
            Agent(id=new_id(), name="x" * 100, owner_uid=1).validate()
        with self.assertRaises(ConfigError):
            Agent(id=new_id(), name="ok", owner_uid=1, runtime="../../bin/sh").validate()

    def test_uid_ranges_unique(self):
        agents = []
        for _ in range(50):
            a = Agent(id=new_id(), name="x", owner_uid=1)
            a.uid_base = allocate_uid_base(a, agents)
            agents.append(a)
        bases = [a.uid_base for a in agents]
        self.assertEqual(len(set(bases)), 50)
        self.assertTrue(all(b >= 0x20000000 and b % 65536 == 0 for b in bases))


class ContainerTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.uid = os.getuid()

    def test_share_inside_home_ok(self):
        p = os.path.join(self.home, "project")
        os.mkdir(p)
        self.assertEqual(validate_share_path(p, self.uid, self.home), os.path.realpath(p))

    def test_share_rejections(self):
        os.mkdir(os.path.join(self.home, ".ssh"))
        os.mkdir(os.path.join(self.home, "real"))
        os.symlink(os.path.join(self.home, "real"), os.path.join(self.home, "link"))
        for bad in (self.home, os.path.join(self.home, ".ssh"), os.path.join(self.home, "link"), "/etc",
                    os.path.join(self.home, "missing")):
            with self.assertRaises(ConfigError, msg=bad):
                validate_share_path(bad, self.uid, self.home)
        with self.assertRaises(ConfigError):
            validate_share_path(os.path.join(self.home, "real"), self.uid + 1, self.home)

    def test_nspawn_isolation_flags(self):
        a = Agent(id=new_id(), name="x", owner_uid=1000, uid_base=0x20010000,
                  shares=[Share("/home/u/p", False, "p")])
        cmd = nspawn_command(a, "/var/lib/iron/agents/x/disk.img", HOST)
        self.assertIn("--private-network", cmd)
        self.assertIn("--private-users=536936448:65536", cmd)
        self.assertIn("--bind-ro=/home/u/p:/home/agent/shared/p:owneridmap", cmd)
        self.assertIn("--resolv-conf=off", cmd)
        self.assertFalse(any("renderD" in c for c in cmd))


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.ctl = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.ctl, "requests"))
        os.makedirs(os.path.join(self.ctl, "responses"))
        self.agent = Agent(id=new_id(), name="A", owner_uid=1000)
        self.q = approvals.ApprovalQueue()

    def write(self, rid, obj):
        with open(os.path.join(self.ctl, "requests", f"{rid}.json"), "w") as f:
            json.dump(obj, f)

    def test_scan_decide_binds_hash(self):
        self.write("abcdef0123", {"kind": "tool", "summary": "use Bash", "detail": "rm -rf build"})
        new = self.q.scan(self.agent, self.ctl)
        self.assertEqual(len(new), 1)
        self.assertEqual(self.q.scan(self.agent, self.ctl), [])  # not re-announced
        req = self.q.decide(new[0]["id"], True, self.ctl)
        with open(os.path.join(self.ctl, "responses", "abcdef0123.json")) as f:
            resp = json.load(f)
        self.assertTrue(resp["allow"])
        self.assertEqual(resp["request_sha256"], req["sha256"])

    def test_elevate_summary_comes_from_argv(self):
        self.write("elev012345", {"kind": "elevate", "summary": "harmless cleanup",
                                  "argv": ["rm", "-rf", "/"]})
        (req,) = self.q.scan(self.agent, self.ctl)
        self.assertIn("rm -rf /", req["summary"])
        self.assertNotIn("harmless", req["summary"])

    def test_malformed_and_oversized_ignored(self):
        with open(os.path.join(self.ctl, "requests", "badjson012.json"), "w") as f:
            f.write("{nope")
        with open(os.path.join(self.ctl, "requests", "huge000000.json"), "w") as f:
            f.write(json.dumps({"summary": "x" * 20000}))
        self.write("elevnoargv", {"kind": "elevate", "summary": "x"})
        self.assertEqual(self.q.scan(self.agent, self.ctl), [])

    def test_symlinked_request_ignored(self):
        target = os.path.join(self.ctl, "secret")
        with open(target, "w") as f:
            json.dump({"summary": "s"}, f)
        os.symlink(target, os.path.join(self.ctl, "requests", "symlink012.json"))
        self.assertEqual(self.q.scan(self.agent, self.ctl), [])


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.outbox = os.path.join(self.root, outputs.OUTBOX)
        os.makedirs(os.path.join(self.outbox, "logs"))
        with open(os.path.join(self.outbox, "report.md"), "w") as f:
            f.write("# result\n")
        with open(os.path.join(self.outbox, "logs", "task-001.log"), "w") as f:
            f.write("ok\n")
        self.secret = os.path.join(self.root, "host-secret")
        with open(self.secret, "w") as f:
            f.write("TOP SECRET")
        os.symlink(self.secret, os.path.join(self.outbox, "leak.txt"))
        os.symlink(self.root, os.path.join(self.outbox, "escape"))
        self.dest = tempfile.mkdtemp()

    def test_list_skips_symlinks(self):
        paths = sorted(f["path"] for f in outputs.list_outputs(self.root))
        self.assertEqual(paths, ["logs/task-001.log", "report.md"])

    def test_export_regular_file(self):
        p = outputs.export(self.root, "report.md", self.dest, os.getuid(), os.getgid())
        with open(p) as f:
            self.assertEqual(f.read(), "# result\n")
        p2 = outputs.export(self.root, "report.md", self.dest, os.getuid(), os.getgid())
        self.assertTrue(p2.endswith("report (1).md"))

    def test_export_refuses_escapes(self):
        for bad in ("leak.txt", "escape/host-secret", "../../host-secret", "logs/../../host-secret", ""):
            with self.assertRaises((OSError, ValueError), msg=bad):
                outputs.export(self.root, bad, self.dest, os.getuid(), os.getgid())

    def test_export_requires_owned_destination(self):
        with self.assertRaises(PermissionError):
            outputs.export(self.root, "report.md", self.dest, os.getuid() + 1, os.getgid())


class FakeRFBServer(threading.Thread):
    def __init__(self, path, w=4, h=2):
        super().__init__(daemon=True)
        self.path, self.w, self.h = path, w, h
        self.srv = socket.socket(socket.AF_UNIX)
        self.srv.bind(path)
        self.srv.listen(1)

    def run(self):
        c, _ = self.srv.accept()
        c.sendall(b"RFB 003.008\n")
        c.recv(12)
        c.sendall(b"\x01\x01")
        c.recv(1)
        c.sendall(struct.pack(">I", 0))
        c.recv(1)
        c.sendall(struct.pack(">HH", self.w, self.h) + b"\x00" * 16 + struct.pack(">I", 4) + b"test")
        c.recv(20)  # SetPixelFormat
        c.recv(8)  # SetEncodings
        c.recv(10)  # FramebufferUpdateRequest
        px = b"".join(struct.pack("<I", (i * 40) << 16 | 0x00AA00 | 0x11) for i in range(self.w * self.h))
        c.sendall(struct.pack(">BxH", 0, 1) + struct.pack(">HHHHi", 0, 0, self.w, self.h, 0) + px)
        c.close()


class RFBTests(unittest.TestCase):
    def test_grab(self):
        path = os.path.join(tempfile.mkdtemp(), "vnc.sock")
        FakeRFBServer(path).start()
        w, h, rgb = rfb.grab(path)
        self.assertEqual((w, h, len(rgb)), (4, 2, 24))
        self.assertEqual(rgb[0:3], bytes([0, 0xAA, 0x11]))
        self.assertEqual(rgb[3:6], bytes([40, 0xAA, 0x11]))


if __name__ == "__main__":
    unittest.main()


class ImageReplacementGuardTests(unittest.TestCase):
    """Rebuilding an image must not pull the base out from under VM agent overlays."""

    def test_dependent_vm_disks(self):
        import shutil
        import subprocess
        from iron_agents import image
        if not shutil.which("qemu-img"):
            self.skipTest("qemu-img not installed")
        with tempfile.TemporaryDirectory() as d:
            images, state = os.path.join(d, "images"), os.path.join(d, "state")
            os.makedirs(os.path.join(images, "base"))
            os.makedirs(os.path.join(images, "other"))
            for img in ("base", "other"):
                subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", os.path.join(images, img, "disk.qcow2"), "1G"],
                               check=True)
            for aid, img in (("a1", "base"), ("a2", "other"), ("a3", "base")):
                os.makedirs(os.path.join(state, aid))
                subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", "-F", "qcow2", "-b",
                                os.path.join(images, img, "disk.qcow2"), os.path.join(state, aid, "disk.qcow2"), "2G"],
                               check=True)
            os.makedirs(os.path.join(state, "c1"))  # container agent: no disk.qcow2
            old = image.IMAGE_DIR
            image.IMAGE_DIR = images
            try:
                self.assertEqual(image.dependent_vm_disks("base", state), ["a1", "a3"])
                self.assertEqual(image.dependent_vm_disks("other", state), ["a2"])
                self.assertEqual(image.dependent_vm_disks("missing", state), [])
            finally:
                image.IMAGE_DIR = old
