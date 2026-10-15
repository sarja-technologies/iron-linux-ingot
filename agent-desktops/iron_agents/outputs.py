"""Reviewing and exporting an agent's results.

Agents publish results in their outbox (/home/agent/outbox inside the agent).
Only regular files reachable without following symlinks are listed or
exported, and exports are written as the requesting host user into a folder
that user chose, so an agent can never write outside it.
"""
import os
import stat

OUTBOX = "home/agent/outbox"
MAX_LIST = 2000


def _open_nofollow_dir(root, rel):
    """Open root/rel component by component with O_NOFOLLOW (no symlink escapes)."""
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in [p for p in rel.split("/") if p]:
            if part in (".", ".."):
                raise ValueError("invalid path")
            nfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nfd
        return fd
    except BaseException:
        os.close(fd)
        raise


def list_outputs(guest_root, outbox=OUTBOX):
    """[{path, size, mtime}] for regular files under the outbox."""
    out = []
    try:
        top = _open_nofollow_dir(guest_root, outbox)
    except (OSError, ValueError):
        return out

    def walk(dfd, prefix):
        for entry in sorted(os.listdir(dfd)):
            if len(out) >= MAX_LIST:
                return
            st = os.stat(entry, dir_fd=dfd, follow_symlinks=False)
            rel = f"{prefix}{entry}"
            if stat.S_ISREG(st.st_mode):
                out.append({"path": rel, "size": st.st_size, "mtime": st.st_mtime})
            elif stat.S_ISDIR(st.st_mode):
                sub = os.open(entry, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dfd)
                try:
                    walk(sub, rel + "/")
                finally:
                    os.close(sub)
    try:
        walk(top, "")
    finally:
        os.close(top)
    return out


def export(guest_root, rel_path, dest_dir, uid, gid, outbox=OUTBOX):
    """Copy outbox/rel_path into dest_dir as uid:gid. Returns the new host path."""
    rel_path = rel_path.strip("/")
    if not rel_path or any(p in ("", ".", "..") for p in rel_path.split("/")):
        raise ValueError("invalid output path")
    parent, name = os.path.split(rel_path)
    dfd = _open_nofollow_dir(guest_root, f"{outbox}/{parent}" if parent else outbox)
    try:
        sfd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
    finally:
        os.close(dfd)
    with os.fdopen(sfd, "rb") as src:
        if not stat.S_ISREG(os.fstat(src.fileno()).st_mode):
            raise ValueError("only regular files can be exported")
        # Pin the destination directory by fd and check ownership on that fd, so a
        # path swapped for a symlink after validation cannot redirect the root write.
        ddfd = os.open(dest_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            st = os.fstat(ddfd)
            if st.st_uid != uid:
                raise PermissionError("destination must be a folder you own")
            base, ext = os.path.splitext(name)
            fname, n = name, 1
            while True:
                try:
                    fd = os.open(fname, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644,
                                 dir_fd=ddfd)
                    break
                except FileExistsError:
                    fname = f"{base} ({n}){ext}"
                    n += 1
            try:
                os.fchown(fd, uid, gid)
                with os.fdopen(fd, "wb") as dst:
                    while True:
                        chunk = src.read(1 << 20)
                        if not chunk:
                            break
                        dst.write(chunk)
            except BaseException:
                os.unlink(fname, dir_fd=ddfd)
                raise
            return os.path.join(os.readlink(f"/proc/self/fd/{ddfd}"), fname)
        finally:
            os.close(ddfd)
