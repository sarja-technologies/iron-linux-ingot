"""Tests for system/bin/iron-update's source parsing and package restriction pin."""
import importlib.machinery
import importlib.util
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_loader = importlib.machinery.SourceFileLoader("iron_update", os.path.join(ROOT, "system/bin/iron-update"))
_spec = importlib.util.spec_from_loader("iron_update", _loader)
upd = importlib.util.module_from_spec(_spec)
_loader.exec_module(upd)


class IronUpdateTests(unittest.TestCase):
    def test_pin_allows_only_ingot_packages_from_the_host(self):
        t = upd.pin_text("apt.example.org")
        stanzas = [s for s in t.split("\n\n") if "Package:" in s]
        self.assertEqual(len(stanzas), 2)
        # allowed names first (500), then everything else from that origin is -1
        self.assertIn("Package: iron-* ingot-* gnotch", stanzas[0])
        self.assertIn("Pin-Priority: 500", stanzas[0])
        self.assertIn("Package: *", stanzas[1])
        self.assertIn("Pin-Priority: -1", stanzas[1])
        for s in stanzas:
            self.assertIn('Pin: origin "apt.example.org"', s)

    def test_read_source(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("# c\nTypes: deb\nURIs: https://h/x\nSuites: ingot\nSigned-By: /usr/share/keyrings/k.gpg\n")
        old = upd.SOURCES
        try:
            upd.SOURCES = f.name
            src = upd.read_source()
            self.assertEqual(src["URIs"], "https://h/x")
            self.assertEqual(src["Signed-By"], "/usr/share/keyrings/k.gpg")
            upd.SOURCES = f.name + ".missing"
            self.assertIsNone(upd.read_source())
        finally:
            upd.SOURCES = old
            os.unlink(f.name)

    def test_own_packages_cover_every_binary_of_the_source(self):
        with open(os.path.join(ROOT, "debian/control")) as f:
            pkgs = [l.split(":", 1)[1].strip() for l in f if l.startswith("Package:")]
        self.assertEqual(sorted(pkgs), sorted(upd.OWN))


if __name__ == "__main__":
    unittest.main()
