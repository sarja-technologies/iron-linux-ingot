"""Unit tests for system/bin/iron-hwprofile against fake sysfs/procfs trees."""
import importlib.machinery
import importlib.util
import json
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_loader = importlib.machinery.SourceFileLoader("iron_hwprofile", os.path.join(ROOT, "system/bin/iron-hwprofile"))
_spec = importlib.util.spec_from_loader("iron_hwprofile", _loader)
hw = importlib.util.module_from_spec(_spec)
_loader.exec_module(hw)


def make_tree(base, files, links=None):
    for path, content in files.items():
        p = os.path.join(base, path.lstrip("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(content)
    for path, target in (links or {}).items():
        p = os.path.join(base, path.lstrip("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        os.makedirs(os.path.join(base, target.lstrip("/")), exist_ok=True)
        os.symlink(os.path.join(base, target.lstrip("/")), p)


def gpu(card, vendor, device, driver):
    files = {f"/sys/class/drm/{card}/device/vendor": vendor, f"/sys/class/drm/{card}/device/device": device,
             f"/sys/class/drm/{card}/device/boot_vga": "1"}
    links = {f"/sys/class/drm/{card}/device/driver": f"/sys/bus/drivers/{driver}"} if driver else {}
    return files, links


class HwProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, files, links=None):
        make_tree(self.root, files, links)
        return hw.detect(self.root)

    def test_nvidia_desktop_high_tier(self):
        g, l = gpu("card1", "0x10de", "0x2503", "nvidia")
        files = {
            "/proc/cpuinfo": "processor : 0\nvendor_id : GenuineIntel\nmodel name : Test CPU\n" * 1,
            "/sys/devices/system/cpu/online": "0-15",
            "/proc/meminfo": "MemTotal:       32000000 kB\n",
            "/dev/dri/renderD128": "", "/dev/kvm": "",
            "/sys/fs/cgroup/cgroup.controllers": "cpu memory io",
            "/sys/class/dmi/id/chassis_type": "3",
            **g,
        }
        r = self.build(files, l)
        self.assertEqual(r["cpu"]["vendor"], "intel")
        self.assertEqual(r["cpu"]["threads"], 16)
        self.assertTrue(r["nvidia"])
        self.assertTrue(r["gpu_acceleration"])
        self.assertFalse(r["laptop"])
        self.assertTrue(r["kvm"] and r["cgroup_v2"])
        self.assertEqual(r["tier"], "high")
        self.assertEqual(hw.dconf_defaults(r), "")

    def test_vm_software_rendering_disables_animations(self):
        g, l = gpu("card0", "0x1234", "0x1111", "bochs-drm")
        r = self.build({
            "/proc/cpuinfo": "processor : 0\nvendor_id : AuthenticAMD\n",
            "/sys/devices/system/cpu/online": "0-3",
            "/proc/meminfo": "MemTotal: 8000000 kB\n",
            "/run/iron-test/virt": "kvm", **g,
        }, l)
        self.assertEqual(r["cpu"]["vendor"], "amd")
        self.assertFalse(r["gpu_acceleration"])
        self.assertEqual(r["virtualization"], "kvm")
        self.assertIn("enable-animations=false", hw.dconf_defaults(r))

    def test_virtio_gpu_without_virgl_is_software(self):
        g, l = gpu("card0", "0x1af4", "0x1050", "virtio_gpu")
        r = self.build({"/proc/cpuinfo": "processor : 0\n", "/proc/meminfo": "MemTotal: 4000000 kB\n",
                        "/dev/dri/renderD128": "",
                        "/sys/kernel/debug/dri/0/virtio-gpu-features": " virgl            : no\n edid             : yes\n",
                        **g}, l)
        self.assertFalse(r["gpu_acceleration"])

    def test_virtio_gpu_features_unreadable_is_software(self):
        g, l = gpu("card0", "0x1af4", "0x1050", "virtio_gpu")
        r = self.build({"/proc/cpuinfo": "processor : 0\n", "/proc/meminfo": "MemTotal: 4000000 kB\n",
                        "/dev/dri/renderD128": "", **g}, l)
        self.assertFalse(r["gpu_acceleration"])

    def test_virtio_gpu_with_virgl_is_accelerated(self):
        g, l = gpu("card0", "0x1af4", "0x1050", "virtio_gpu")
        r = self.build({"/proc/cpuinfo": "processor : 0\n", "/proc/meminfo": "MemTotal: 4000000 kB\n",
                        "/dev/dri/renderD128": "",
                        "/sys/kernel/debug/dri/0/virtio-gpu-features": " virgl            : yes\n",
                        **g}, l)
        self.assertTrue(r["gpu_acceleration"])

    def virtio_pci_gpu(self, features):
        # Real layout (observed in an Ingot VM): card -> PCI device bound to
        # virtio-pci; virtio_gpu is bound to device/virtio0 below it.
        files = {"/sys/class/drm/card1/device/vendor": "0x1af4", "/sys/class/drm/card1/device/device": "0x1050",
                 "/sys/class/drm/card1/device/boot_vga": "1",
                 "/sys/class/drm/card1/device/virtio0/features": features,
                 "/proc/cpuinfo": "processor : 0\n", "/proc/meminfo": "MemTotal: 4000000 kB\n",
                 "/dev/dri/renderD128": ""}
        links = {"/sys/class/drm/card1/device/driver": "/sys/bus/pci/drivers/virtio-pci",
                 "/sys/class/drm/card1/device/virtio0/driver": "/sys/bus/virtio/drivers/virtio_gpu"}
        return self.build(files, links)

    def test_virtio_pci_gpu_without_virgl_is_software(self):
        r = self.virtio_pci_gpu("0100000000000000000000000000110010000000100000000000000000000000")
        self.assertEqual(r["gpus"][0]["driver"], "virtio_gpu")
        self.assertTrue(r["gpus"][0]["software_only"])
        self.assertFalse(r["gpu_acceleration"])

    def test_virtio_pci_gpu_with_virgl_is_accelerated(self):
        r = self.virtio_pci_gpu("1100000000000000000000000000110010000000100000000000000000000000")
        self.assertTrue(r["gpu_acceleration"])

    def test_virtio_pci_gpu_with_context_init_is_accelerated(self):
        r = self.virtio_pci_gpu("0101100000000000000000000000110010000000100000000000000000000000")
        self.assertTrue(r["gpu_acceleration"])

    def test_arm64_pi_low_tier(self):
        g, l = gpu("card1", "", "", "v3d")
        r = self.build({
            "/proc/cpuinfo": "processor : 0\nCPU implementer : 0x41\nprocessor : 1\nModel : Raspberry Pi 4 Model B\n",
            "/sys/devices/system/cpu/online": "0-3",
            "/proc/meminfo": "MemTotal: 3900000 kB\n",
            "/proc/device-tree/model": "Raspberry Pi 4 Model B Rev 1.4",
            "/dev/dri/renderD128": "",
            "/run/iron-test/arch": "aarch64", **g,
        }, l)
        self.assertEqual(r["cpu"]["vendor"], "arm")
        self.assertTrue(r["raspberry_pi"])
        self.assertEqual(r["gpus"][0]["vendor"], "broadcom")
        self.assertEqual(r["tier"], "low")
        d = hw.dconf_defaults(r)
        self.assertIn("index-recursive-directories=@as []", d)

    def test_laptop_battery(self):
        r = self.build({"/proc/cpuinfo": "processor : 0\n", "/proc/meminfo": "MemTotal: 16000000 kB\n",
                        "/sys/class/power_supply/BAT0/status": "Discharging"})
        self.assertTrue(r["laptop"])

    def test_apply_writes_json_atomically(self):
        r = self.build({"/proc/cpuinfo": "processor : 0\n", "/proc/meminfo": "MemTotal: 1000 kB\n"})
        run_dir = os.path.join(self.root, "out-run")
        dconf_dir = os.path.join(self.root, "out-dconf")
        hw.apply(r, run_dir=run_dir, dconf_dir=dconf_dir, compile_db=False)
        with open(os.path.join(run_dir, "hardware.json")) as f:
            self.assertEqual(json.load(f)["tier"], "low")
        self.assertTrue(os.path.exists(os.path.join(dconf_dir, "00-hwprofile")))
        self.assertFalse(os.path.exists(os.path.join(run_dir, ".hardware.json.tmp")))


if __name__ == "__main__":
    unittest.main()
