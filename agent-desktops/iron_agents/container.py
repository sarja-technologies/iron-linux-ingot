"""Container backend: systemd-nspawn with a private user namespace.

Isolation model (each enforced by the kernel, not by the UI):
  * user namespace: container root is a high, per-agent host UID range, so it
    has no privileges over host files or processes;
  * mount namespace + private disk image: only the agent's own ext4 image and
    explicitly granted folders are visible; image size caps storage;
  * network namespace: no network unless the agent is granted "internet"
    (then user-mode networking via pasta, with no route to host services);
  * cgroup v2 (transient unit in iron-agents.slice): cpuset, CPU quota, memory
    hard limit without swap escape, task limit, optional runtime limit;
  * device policy: no host devices except GPU render nodes when granted.
"""
import os
import shutil
import subprocess
import time

from . import storage, units
from .config import RUN_DIR, ConfigError

UID_RANGE = 65536
UID_BASE_MIN = 0x20000000  # well clear of normal users and systemd's DynamicUser range
AGENT_UID = 1000  # the unprivileged "agent" user inside the image
GUEST_DISPLAY = "/run/iron-agent/display"
GUEST_CONTROL = "/run/iron-agent/control"


def machine_name(agent_id):
    return f"iron-{agent_id}"


def allocate_uid_base(agent, others):
    """Stable, collision-free UID range per agent (kept across restarts so the
    one-time ownership shift is not repeated)."""
    if agent.uid_base:
        return agent.uid_base
    used = {a.uid_base for a in others if a.uid_base}
    slot = int(agent.id[1:], 16) % 4096
    for i in range(4096):
        base = UID_BASE_MIN + ((slot + i) % 4096) * UID_RANGE
        if base not in used:
            return base
    raise ConfigError("no free user-namespace range")


def run_dir(agent):
    return os.path.join(RUN_DIR, agent.id)


def prepare_run_dir(agent):
    """/run/iron/agents/<id> (owner:agent-root 0750) with display/ and control/."""
    d = run_dir(agent)
    os.makedirs(RUN_DIR, mode=0o711, exist_ok=True)
    os.makedirs(d, exist_ok=True)
    os.chown(d, agent.owner_uid, agent.uid_base)
    os.chmod(d, 0o750)
    for sub, mode in (("display", 0o755), ("control", 0o755), ("control/inbox", 0o750),
                      ("control/requests", 0o1733), ("control/responses", 0o755)):
        p = os.path.join(d, sub)
        os.makedirs(p, exist_ok=True)
        # The display server runs as the unprivileged agent user inside the container.
        owner = agent.uid_base + (AGENT_UID if sub == "display" else 0)
        os.chown(p, owner, owner)
        os.chmod(p, mode)
    return d


def _disk(store, agent):
    return store.path(agent.id, "disk.img")


def ensure_disk(store, agent):
    disk = _disk(store, agent)
    if not os.path.exists(disk):
        storage.create_container_disk(disk, agent.image, agent.resources.storage_gib)
    elif os.path.getsize(disk) < (agent.resources.storage_gib << 30):
        storage.resize_container_disk(disk, agent.resources.storage_gib)
    return disk


def prepare_shares(store, agent, disk):
    """Create /home/agent/shared/<name> owned by the agent user inside the image,
    so `owneridmap` maps exactly that user to the granting host user."""
    if not agent.shares:
        return
    mnt = store.path(agent.id, "mnt-prepare")
    os.makedirs(mnt, exist_ok=True)
    subprocess.run(["mount", "-o", "loop,nodev,nosuid", disk, mnt], check=True)
    try:
        root_uid = os.stat(mnt).st_uid  # 0 before the first boot, uid_base after the shift
        uid = root_uid + AGENT_UID
        base = os.path.join(mnt, "home/agent/shared")
        os.makedirs(base, exist_ok=True)
        os.chown(base, uid, uid)
        for s in agent.shares:
            p = os.path.join(base, s.name)
            if os.path.islink(p):
                os.unlink(p)
            os.makedirs(p, exist_ok=True)
            os.chown(p, uid, uid)
    finally:
        subprocess.run(["umount", mnt], check=False)


def validate_share_path(path, owner_uid, home):
    """A share must be an existing directory the owner owns, inside their home,
    and not a credentials/config store."""
    real = os.path.realpath(path)
    if real != os.path.abspath(path):
        raise ConfigError("shared folder must not be (or be inside) a symlink")
    if not os.path.isdir(real):
        raise ConfigError("shared folder must be an existing directory")
    st = os.stat(real)
    if st.st_uid != owner_uid:
        raise ConfigError("you can only share folders you own")
    home = os.path.realpath(home)
    if real == home or not real.startswith(home + os.sep):
        raise ConfigError("share a folder inside your home directory, not the home directory itself")
    rel = os.path.relpath(real, home).split(os.sep)
    if rel[0] in (".ssh", ".gnupg", ".config", ".local", ".mozilla", ".pki", ".password-store", ".aws", ".kube"):
        raise ConfigError(f"~/{rel[0]} holds credentials or settings and cannot be shared")
    return real


def nspawn_command(agent, disk, host):
    r = agent.resources
    rd = run_dir(agent)
    cmd = ["systemd-nspawn", "--quiet", "--keep-unit", "--register=yes",
           f"--machine={machine_name(agent.id)}", f"--image={disk}", "--boot",
           "--notify-ready=yes",
           f"--private-users={agent.uid_base}:{UID_RANGE}", "--private-users-ownership=chown",
           "--private-network", "--link-journal=no", "--timezone=copy",
           f"--resolv-conf={'copy-host' if r.network == 'internet' else 'off'}",
           f"--hostname={machine_name(agent.id)}",
           f"--bind={rd}/display:{GUEST_DISPLAY}",
           f"--bind={rd}/control:{GUEST_CONTROL}",
           "--setenv=IRON_AGENT=1"]
    for s in agent.shares:
        flag = "--bind" if s.writable else "--bind-ro"
        cmd.append(f"{flag}={s.host_path}:/home/agent/shared/{s.name}:owneridmap")
    if r.gpu == "shared":
        for node in host.render_nodes:
            cmd.append(f"--bind=/dev/dri/{node}")
    return cmd


def start(store, agent, host):
    disk = ensure_disk(store, agent)
    prepare_shares(store, agent, disk)
    prepare_run_dir(agent)
    gpu_devs = [f"/dev/dri/{n}" for n in host.render_nodes] if agent.resources.gpu == "shared" else []
    props = units.cgroup_properties(agent.resources, host.threads, gpu_devices=gpu_devs)
    props += ["Delegate=yes", "KillMode=mixed", "DevicePolicy=closed",
              "DeviceAllow=/dev/net/tun rwm", "DeviceAllow=char-pts rw",
              # nspawn itself attaches the disk image via loop devices; the
              # container payload has no loop nodes and cannot create any.
              "DeviceAllow=/dev/loop-control rw", "DeviceAllow=block-loop rw", "DeviceAllow=block-blkext rw",
              "TimeoutStartSec=180", "TimeoutStopSec=30"]
    units.systemd_run(agent.id, nspawn_command(agent, disk, host), props,
                      description=f"Iron Agent Desktop: {agent.name}", notify=True)
    if agent.resources.network == "internet":
        start_network(agent)


def leader_pid(agent):
    r = subprocess.run(["machinectl", "show", machine_name(agent.id), "-p", "Leader", "--value"],
                       capture_output=True, text=True)
    try:
        return int(r.stdout.strip())
    except ValueError:
        return 0


def start_network(agent):
    """User-mode networking (pasta) bound to the agent unit's lifetime.
    --no-map-gw: the agent cannot reach services listening on the host."""
    pid = leader_pid(agent)
    if not pid:
        raise ConfigError("container did not report a leader process")
    if not shutil.which("pasta"):
        raise ConfigError("internet access needs the 'passt' package (pasta)")
    unit = f"iron-agent-{agent.id}-net.service"
    subprocess.run(["systemd-run", f"--unit={unit}", f"--slice={units.SLICE}", "--collect", "--quiet",
                    f"--property=BindsTo={units.unit_name(agent.id)}",
                    f"--property=After={units.unit_name(agent.id)}",
                    "--", "pasta", "--foreground", "--quiet", "--config-net", "--no-map-gw",
                    "--netns", f"/proc/{pid}/ns/net", "--userns", f"/proc/{pid}/ns/user"],
                   check=True, capture_output=True, text=True)


def stop(agent, timeout=30):
    subprocess.run(["machinectl", "poweroff", machine_name(agent.id)], capture_output=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if units.unit_state(agent.id)["active"] in ("inactive", "failed", ""):
            return
        time.sleep(0.5)
    units.stop(agent.id)


def pause(agent):
    units.freeze(agent.id)


def resume(agent):
    units.thaw(agent.id)


def revoke_share_live(agent, name):
    """Unmount a granted folder inside the running container immediately."""
    pid = leader_pid(agent)
    if pid:
        subprocess.run(["nsenter", "-t", str(pid), "-m", "--", "umount", "-l", f"/home/agent/shared/{name}"],
                       capture_output=True)


def guest_root(agent):
    """Host path to the running container's root filesystem (via its leader)."""
    pid = leader_pid(agent)
    return f"/proc/{pid}/root" if pid else None


def snapshot(store, agent, name):
    if units.unit_state(agent.id)["active"] == "active":
        raise ConfigError("stop the agent before taking a container snapshot")
    snapdir = store.path(agent.id, "snapshots")
    os.makedirs(snapdir, exist_ok=True)
    storage.snapshot_container(_disk(store, agent), os.path.join(snapdir, f"{name}.img"))


def restore(store, agent, name):
    if units.unit_state(agent.id)["active"] == "active":
        raise ConfigError("stop the agent before restoring a snapshot")
    storage.restore_container(store.path(agent.id, "snapshots", f"{name}.img"), _disk(store, agent))
