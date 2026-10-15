"""Per-agent disk images. The image size is the agent's hard storage limit."""
import os
import shutil
import subprocess

from .config import IMAGE_DIR, ConfigError


def run(cmd, **kw):
    kw.setdefault("check", True)
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    return subprocess.run(cmd, **kw)


def image_paths(image="base"):
    base = os.path.join(IMAGE_DIR, image)
    return {
        "dir": base,
        "rootfs": os.path.join(base, "rootfs"),
        "qcow2": os.path.join(base, "disk.qcow2"),
        "kernel": os.path.join(base, "vmlinuz"),
        "initrd": os.path.join(base, "initrd.img"),
        "info": os.path.join(base, "image.json"),
    }


def image_ready(image="base", backend="container"):
    p = image_paths(image)
    if backend == "container":
        return os.path.isfile(os.path.join(p["rootfs"], "usr/lib/iron-agent/iron-agent-runner"))
    return all(os.path.isfile(p[k]) for k in ("qcow2", "kernel", "initrd"))


def create_container_disk(path, image, size_gib):
    """Sparse ext4 image populated from the base rootfs (no mounting needed)."""
    src = image_paths(image)["rootfs"]
    if not os.path.isdir(src):
        raise ConfigError(f"agent image '{image}' is not installed (iron-agent image build)")
    tmp = path + ".creating"
    if os.path.exists(tmp):
        os.unlink(tmp)
    with open(tmp, "wb") as f:
        f.truncate(size_gib << 30)
    try:
        run(["mkfs.ext4", "-q", "-F", "-L", "iron-agent", "-E", "root_owner=0:0", "-d", src, tmp])
    except subprocess.CalledProcessError as e:
        os.unlink(tmp)
        raise ConfigError(f"could not create agent disk: {e.stderr.strip()}") from e
    os.replace(tmp, path)


def create_vm_disk(path, image, size_gib):
    base = image_paths(image)["qcow2"]
    if not os.path.isfile(base):
        raise ConfigError(f"VM image '{image}' is not installed (iron-agent image build --vm)")
    run(["qemu-img", "create", "-q", "-f", "qcow2", "-F", "qcow2", "-b", base, path, f"{size_gib}G"])


def disk_usage(path):
    """(apparent_bytes, allocated_bytes) for a sparse image."""
    try:
        st = os.stat(path)
        return st.st_size, st.st_blocks * 512
    except OSError:
        return 0, 0


def resize_container_disk(path, size_gib):
    cur = os.path.getsize(path)
    if (size_gib << 30) < cur:
        raise ConfigError("agent storage can grow but not shrink")
    with open(path, "r+b") as f:
        f.truncate(size_gib << 30)
    run(["e2fsck", "-p", "-f", path], check=False)
    run(["resize2fs", path])


def snapshot_container(disk, dest):
    run(["cp", "--sparse=always", "--reflink=auto", disk, dest])


def restore_container(snap, disk):
    tmp = disk + ".restoring"
    run(["cp", "--sparse=always", "--reflink=auto", snap, tmp])
    os.replace(tmp, disk)


class ReadOnlyMount:
    """Loop-mount a stopped container disk read-only (for reviewing outputs)."""

    def __init__(self, disk, mountpoint):
        self.disk, self.mnt = disk, mountpoint

    def __enter__(self):
        os.makedirs(self.mnt, exist_ok=True)
        run(["mount", "-o", "loop,ro,nodev,nosuid,noexec", self.disk, self.mnt])
        return self.mnt

    def __exit__(self, *exc):
        run(["umount", self.mnt], check=False)


def remove_tree(path):
    if os.path.isdir(path) and not os.path.ismount(path):
        shutil.rmtree(path)
