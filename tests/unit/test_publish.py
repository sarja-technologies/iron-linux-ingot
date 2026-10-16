"""Tests for tools/ingot-publish: signing, version policy, yank, retention, tamper detection."""
import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_loader = importlib.machinery.SourceFileLoader("ingot_publish", os.path.join(ROOT, "tools/ingot-publish"))
_spec = importlib.util.spec_from_loader("ingot_publish", _loader)
pub = importlib.util.module_from_spec(_spec)
_loader.exec_module(pub)

HAVE_TOOLS = all(shutil.which(t) for t in ("gpg", "gpgv", "dpkg-deb", "apt-ftparchive"))


def make_deb(outdir, name, version, arch="all", payload=""):
    d = tempfile.mkdtemp(dir=outdir)
    os.makedirs(os.path.join(d, "DEBIAN"))
    with open(os.path.join(d, "DEBIAN", "control"), "w") as f:
        f.write(f"Package: {name}\nVersion: {version}\nArchitecture: {arch}\n"
                f"Maintainer: Test <t@example.invalid>\nDescription: test package\n")
    os.makedirs(os.path.join(d, "usr/share/doc", name))
    with open(os.path.join(d, "usr/share/doc", name, "v"), "w") as f:
        f.write(version + payload)
    out = os.path.join(outdir, f"{name}_{version}_{arch}.deb")
    subprocess.run(["dpkg-deb", "--root-owner-group", "-Zgzip", "-b", d, out], check=True, capture_output=True)
    shutil.rmtree(d)
    return out


def make_key(home, uid):
    os.makedirs(home, mode=0o700)
    subprocess.run(["gpg", "--homedir", home, "--batch", "--pinentry-mode", "loopback", "--passphrase", "",
                    "--quick-gen-key", uid, "ed25519", "sign", "1d"], check=True, capture_output=True)


@unittest.skipUnless(HAVE_TOOLS, "gpg/dpkg-deb/apt-ftparchive not available")
class PublishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.keys = os.path.join(cls.tmp, "keys")
        make_key(cls.keys, "Ingot test archive")
        cls.other = os.path.join(cls.tmp, "other")
        make_key(cls.other, "Attacker")

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["gpgconf", "--homedir", cls.keys, "--kill", "gpg-agent"], capture_output=True)
        subprocess.run(["gpgconf", "--homedir", cls.other, "--kill", "gpg-agent"], capture_output=True)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.d = tempfile.mkdtemp(dir=self.tmp)
        self.repo = pub.Repo(os.path.join(self.d, "repo"), "ingot", self.keys, keep=2)

    def packages(self, arch="all"):
        with open(os.path.join(self.repo.root, "dists/ingot/main", f"binary-{arch}", "Packages")) as f:
            return f.read()

    def test_add_sign_verify(self):
        self.repo.add([make_deb(self.d, "iron-shell", "1.0"), make_deb(self.d, "iron-agent", "1.0", "amd64")])
        self.repo.verify()
        self.assertIn("Package: iron-shell", self.packages("all"))
        # binary-amd64 lists both arch:all and amd64 packages; arm64 only arch:all.
        self.assertIn("Package: iron-agent", self.packages("amd64"))
        self.assertIn("Package: iron-shell", self.packages("amd64"))
        self.assertNotIn("Package: iron-agent", self.packages("arm64"))
        with open(os.path.join(self.repo.root, "dists/ingot/Release")) as f:
            rel = f.read()
        self.assertIn("Origin: Iron Linux", rel)
        self.assertIn("Suite: ingot", rel)

    def test_refuses_version_regression_and_replacement(self):
        self.repo.add([make_deb(self.d, "iron-shell", "2.0")])
        with self.assertRaisesRegex(pub.PublishError, "not newer"):
            self.repo.add([make_deb(self.d, "iron-shell", "1.9")])
        with self.assertRaisesRegex(pub.PublishError, "not newer"):
            self.repo.add([make_deb(tempfile.mkdtemp(dir=self.d), "iron-shell", "2.0~rc1")])
        # same name, different content: must not silently replace a release
        other = tempfile.mkdtemp(dir=self.d)
        with self.assertRaisesRegex(pub.PublishError, "bump the version"):
            self.repo.add([make_deb(other, "iron-shell", "2.0", payload="rebuilt")])
        # byte-identical re-publish is a no-op
        self.repo.add([os.path.join(self.d, "iron-shell_2.0_all.deb")])
        self.repo.verify()

    def test_keeps_history_for_rollback_and_yank(self):
        for v in ("1.0", "1.1", "1.2"):
            self.repo.add([make_deb(tempfile.mkdtemp(dir=self.d), "iron-shell", v)])
        idx = self.packages()
        self.assertIn("Version: 1.2", idx)
        self.assertIn("Version: 1.1", idx)  # keep=2: previous release stays installable
        self.assertNotIn("Version: 1.0", idx)
        self.repo.yank("iron-shell", "1.2")
        idx = self.packages()
        self.assertNotIn("Version: 1.2", idx)
        self.assertIn("Version: 1.1", idx)
        self.assertTrue(os.path.exists(os.path.join(self.repo.root, "pool/main/i/iron-shell/iron-shell_1.2_all.deb")))
        self.repo.verify()
        # a yanked version still blocks re-use of its number
        with self.assertRaisesRegex(pub.PublishError, "not newer"):
            self.repo.add([make_deb(tempfile.mkdtemp(dir=self.d), "iron-shell", "1.2~fix")])

    def test_verify_detects_tampering(self):
        self.repo.add([make_deb(self.d, "iron-shell", "1.0")])
        deb = os.path.join(self.repo.root, "pool/main/i/iron-shell/iron-shell_1.0_all.deb")
        with open(deb, "ab") as f:
            f.write(b"x")
        with self.assertRaisesRegex(pub.PublishError, "checksum mismatch"):
            self.repo.verify()

    def test_verify_rejects_foreign_signature(self):
        self.repo.add([make_deb(self.d, "iron-shell", "1.0")])
        trusted = os.path.join(self.repo.root, "iron-archive-keyring.gpg")
        keep = os.path.join(self.d, "trusted.gpg")
        shutil.copy(trusted, keep)
        evil = pub.Repo(self.repo.root, "ingot", self.other)
        evil.resign()  # re-signed by a key the client does not trust
        with self.assertRaisesRegex(pub.PublishError, "does not verify"):
            self.repo.verify(keyring=keep)


if __name__ == "__main__":
    unittest.main()
